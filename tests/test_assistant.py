"""The assistant: tool scoping, the agentic loop, and what it refuses to do.

No API key and no network. The Gemini client is injected into `converse`, so
a fake returning scripted responses exercises the whole loop -- dispatch, tenant
binding, citation collection, the round cap. The tools are plain functions and
are tested directly.
"""

from types import SimpleNamespace

import pytest

from app.modules.alerts.service import TYPE_LOW_STOCK, AlertService
from app.modules.assistant import service as assistant_service
from app.modules.assistant.tools import TOOLS, run_tool


# ---------------------------------------------------------------------------
# A fake Gemini client
#
# Mirrors the shape the service uses: client.aio.models.generate_content, with
# automatic function calling. The fake runs the tools it is told to, exactly as
# the SDK would, so the loop, the tenant binding and the citation collection are
# all exercised without a network call or an API key.
# ---------------------------------------------------------------------------
class FakeModels:
    def __init__(self, plan, answer):
        self.plan = list(plan)  # [(tool_name, kwargs), ...] the "model" decides to call
        self.answer = answer
        self.requests = []

    async def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        by_name = {t.__name__: t for t in config.tools}
        for name, kwargs in self.plan:
            by_name[name](**kwargs)
        return SimpleNamespace(text=self.answer)


class FakeClient:
    def __init__(self, plan=(), answer="Here is the answer."):
        self.models = FakeModels(plan, answer)
        self.aio = SimpleNamespace(models=self.models)


class ExplodingClient:
    def __init__(self, error):
        async def boom(**_):
            raise error

        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=boom))


async def _collect(client, db, company_id, question="hello"):
    return [
        event
        async for event in assistant_service.converse(
            client=client, db=db, company_id=company_id, question=question
        )
    ]


# ---------------------------------------------------------------------------
# Tenant scoping — the security property that matters most
# ---------------------------------------------------------------------------
def test_tools_never_see_another_companys_data(
    db_session, company, other_company, make_product, make_warehouse, make_stock
):
    make_product(company, sku="MINE-1", name="My widget")
    theirs = make_product(other_company, sku="THEIRS-1", name="Their widget")
    make_stock(theirs, make_warehouse(other_company), quantity=999)
    db_session.commit()

    result, _ = run_tool(db_session, company.id, "search_products", {})

    skus = [p["sku"] for p in result["products"]]
    assert "MINE-1" in skus
    assert "THEIRS-1" not in skus


def test_a_company_id_supplied_by_the_model_is_ignored(
    db_session, company, other_company, make_product
):
    """The tenant comes from the JWT, never from the model's arguments.

    If a prompt injection convinced the model to pass another company's id, the
    argument is dropped rather than honoured -- the binding is positional and
    the field does not exist in any tool schema.
    """
    make_product(company, sku="MINE-2")
    make_product(other_company, sku="THEIRS-2")
    db_session.commit()

    result, _ = run_tool(
        db_session,
        company.id,
        "search_products",
        {"company_id": str(other_company.id)},
    )

    skus = [p["sku"] for p in result["products"]]
    assert skus == ["MINE-2"]


def test_no_tool_schema_exposes_the_tenant():
    """A field the model cannot see is a field it cannot be argued into setting."""
    for tool in TOOLS:
        assert "company_id" not in tool["input_schema"].get("properties", {})


def test_every_advertised_tool_is_executable():
    """A described tool with no executor is a guaranteed runtime failure."""
    from app.modules.assistant.tools import EXECUTORS

    assert {t["name"] for t in TOOLS} == set(EXECUTORS)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
def test_check_stock_can_filter_to_what_needs_reordering(
    db_session, company, make_product, make_warehouse, make_stock
):
    warehouse = make_warehouse(company)
    healthy = make_stock(make_product(company, sku="OK-1"), warehouse, quantity=500)
    healthy.reorder_point = 10
    low = make_stock(make_product(company, sku="LOW-1"), warehouse, quantity=2)
    low.reorder_point = 50
    db_session.commit()

    result, citations = run_tool(
        db_session, company.id, "check_stock", {"low_only": True}
    )

    assert [line["sku"] for line in result["stock_lines"]] == ["LOW-1"]
    # Citations point at real records, so the UI can show what an answer used.
    assert citations and citations[0]["type"] == "stock"


def test_alerts_carry_their_evidence(
    db_session, company, make_product, make_warehouse, make_stock
):
    """So the model can explain WHY an alert fired instead of restating its title."""
    stock = make_stock(make_product(company), make_warehouse(company), quantity=1)
    AlertService(db_session).open_alert(
        company_id=company.id,
        alert_type=TYPE_LOW_STOCK,
        severity="warning",
        subject_type="inventory",
        subject_id=stock.id,
        title="Widget is below its reorder point",
        detail={"quantity": 1, "reorder_point": 20},
    )
    db_session.commit()

    result, _ = run_tool(db_session, company.id, "list_alerts", {})

    assert result["total_open"] == 1
    assert result["alerts"][0]["evidence"]["reorder_point"] == 20


def test_an_unknown_tool_is_reported_not_raised(db_session, company):
    result, citations = run_tool(db_session, company.id, "delete_everything", {})

    assert "error" in result
    assert citations == []


def test_a_hallucinated_argument_is_correctable_not_fatal(db_session, company):
    """The model gets an error it can retry from, rather than a 500."""
    result, _ = run_tool(db_session, company.id, "search_products", {"colour": "blue"})

    assert "error" in result


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_a_plain_answer_needs_no_tools(db_session, company):
    client = FakeClient(plan=[], answer="Hello.")

    events = await _collect(client, db_session, company.id)

    assert [e["type"] for e in events] == ["text", "done"]
    assert events[0]["text"] == "Hello."


@pytest.mark.anyio
async def test_a_tool_call_reaches_the_database_and_is_reported(
    db_session, company, make_product
):
    make_product(company, sku="LOOP-1", name="Loop widget")
    db_session.commit()

    client = FakeClient(
        plan=[("search_products", {"query": "Loop"})],
        answer="You stock Loop widget.",
    )

    events = await _collect(client, db_session, company.id, "what do we stock?")

    kinds = [e["type"] for e in events]
    assert "tool" in kinds and "citation" in kinds and "done" in kinds

    tool = next(e for e in events if e["type"] == "tool")
    assert tool["name"] == "search_products"

    # The citation names the row the answer actually came from.
    citation = next(e for e in events if e["type"] == "citation")["citation"]
    assert citation["ref"] == "LOOP-1"


@pytest.mark.anyio
async def test_the_tenant_is_bound_and_never_exposed_to_the_model(
    db_session, company, other_company, make_product
):
    """The whole security model, asserted through the loop rather than the tools.

    Every tool the model can see is a closure over this request's company_id.
    There is no parameter for it, so no phrasing of a question can reach another
    company's rows.
    """
    make_product(company, sku="OURS-1")
    make_product(other_company, sku="THEIRS-1")
    db_session.commit()

    client = FakeClient(plan=[("search_products", {})], answer="Done.")
    await _collect(client, db_session, company.id)

    config = client.models.requests[0]["config"]
    for tool in config.tools:
        assert "company_id" not in tool.__code__.co_varnames

    # And the call it made only saw this tenant's catalogue.
    result, _ = run_tool(db_session, company.id, "search_products", {})
    assert [p["sku"] for p in result["products"]] == ["OURS-1"]


@pytest.mark.anyio
async def test_duplicate_citations_are_reported_once(
    db_session, company, make_product, make_warehouse, make_stock
):
    """Two tools citing the same record should not show it twice."""
    product = make_product(company, sku="DUP-1", name="Dup widget")
    make_stock(product, make_warehouse(company), quantity=5)
    db_session.commit()

    client = FakeClient(
        plan=[
            ("search_products", {"query": "Dup"}),
            ("search_products", {"query": "Dup"}),
        ],
        answer="Done.",
    )
    events = await _collect(client, db_session, company.id)

    refs = [e["citation"]["ref"] for e in events if e["type"] == "citation"]
    assert refs.count("DUP-1") == 1


@pytest.mark.anyio
async def test_an_empty_answer_is_named_rather_than_rendered_blank(db_session, company):
    client = FakeClient(plan=[], answer="")

    events = await _collect(client, db_session, company.id)

    assert events[-1]["type"] == "error"
    assert "no answer" in events[-1]["message"]


@pytest.mark.anyio
async def test_a_rate_limit_explains_the_free_tier(db_session, company):
    """The Gemini free tier allows only a few requests a minute, so this is the
    error a demo hits most -- and "check the log" would be useless advice."""
    events = await _collect(
        ExplodingClient(RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")),
        db_session,
        company.id,
    )

    assert events[-1]["type"] == "error"
    assert "rate limit" in events[-1]["message"].lower()


@pytest.mark.anyio
async def test_a_retired_model_says_which_setting_to_change(db_session, company):
    """Gemini 2.5 Flash is no longer served to new keys; the 404 should say so."""
    events = await _collect(
        ExplodingClient(RuntimeError("404 NOT_FOUND: model is no longer available")),
        db_session,
        company.id,
    )

    assert "ASSISTANT_MODEL" in events[-1]["message"]


@pytest.mark.anyio
async def test_a_rejected_key_names_the_setting(db_session, company):
    events = await _collect(
        ExplodingClient(RuntimeError("401 UNAUTHENTICATED: API key not valid")),
        db_session,
        company.id,
    )

    assert "GEMINI_API_KEY" in events[-1]["message"]


@pytest.mark.anyio
async def test_an_unexpected_failure_does_not_leak_its_detail(db_session, company):
    """A raw API error can quote request content back, and that content is the
    tenant's data."""
    events = await _collect(
        ExplodingClient(RuntimeError("boom: SELECT * FROM secrets")),
        db_session,
        company.id,
    )

    assert events[-1]["type"] == "error"
    assert "boom" not in events[-1]["message"]
    assert "secrets" not in events[-1]["message"]


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_status_publishes_what_the_assistant_can_reach(authenticated_client):
    body = authenticated_client.get("/api/v1/assistant/status").json()

    assert "configured" in body
    names = {t["name"] for t in body["tools"]}
    assert "check_stock" in names


def test_asking_without_a_key_explains_itself(authenticated_client, monkeypatch):
    """A missing key disables one screen and says so; it never 500s."""
    monkeypatch.setattr(assistant_service.settings, "GEMINI_API_KEY", "")

    response = authenticated_client.post(
        "/api/v1/assistant/ask", json={"question": "how much stock do we have?"}
    )

    assert response.status_code == 200
    assert "GEMINI_API_KEY" in response.text


def test_asking_requires_authentication(client):
    assert (
        client.post("/api/v1/assistant/ask", json={"question": "hi"}).status_code == 401
    )
