"""The assistant: tool scoping, the agentic loop, and what it refuses to do.

No API key and no network. The Anthropic client is injected into `converse`, so
a fake returning scripted responses exercises the whole loop -- dispatch, tenant
binding, citation collection, the round cap. The tools are plain functions and
are tested directly.
"""

import json
from types import SimpleNamespace

import pytest

from app.modules.alerts.service import TYPE_LOW_STOCK, AlertService
from app.modules.assistant import service as assistant_service
from app.modules.assistant.tools import TOOLS, run_tool


# ---------------------------------------------------------------------------
# A fake Anthropic client
# ---------------------------------------------------------------------------
class _Block(SimpleNamespace):
    pass


def _text_block(text):
    return _Block(type="text", text=text)


def _tool_block(name, arguments, block_id="toolu_1"):
    return _Block(type="tool_use", name=name, input=arguments, id=block_id)


class FakeStream:
    def __init__(self, message):
        self._message = message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    @property
    def text_stream(self):
        async def gen():
            for block in self._message.content:
                if block.type == "text":
                    yield block.text

        return gen()

    async def get_final_message(self):
        return self._message


class FakeMessages:
    def __init__(self, turns):
        self._turns = list(turns)
        self.requests = []

    def stream(self, **kwargs):
        # Snapshot the message list. The loop appends to the same list object
        # across rounds, so storing the reference would record what the
        # conversation became rather than what this request actually sent.
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        if not self._turns:
            raise AssertionError("Fake client ran out of scripted turns")
        return FakeStream(self._turns.pop(0))


class FakeClient:
    def __init__(self, turns):
        self.messages = FakeMessages(turns)


def _turn(content, stop_reason="end_turn"):
    return _Block(content=content, stop_reason=stop_reason)


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
    client = FakeClient([_turn([_text_block("Hello.")])])

    events = await _collect(client, db_session, company.id)

    assert [e["type"] for e in events] == ["text", "done"]
    assert events[0]["text"] == "Hello."


@pytest.mark.anyio
async def test_a_tool_call_is_executed_and_fed_back(db_session, company, make_product):
    make_product(company, sku="LOOP-1", name="Loop widget")
    db_session.commit()

    client = FakeClient(
        [
            _turn([_tool_block("search_products", {"query": "Loop"})], "tool_use"),
            _turn([_text_block("You stock Loop widget.")]),
        ]
    )

    events = await _collect(client, db_session, company.id, "what do we stock?")

    kinds = [e["type"] for e in events]
    assert "tool" in kinds and "citation" in kinds and "done" in kinds
    # The envelope's kind must survive the citation's own `type` field.
    citation = next(e for e in events if e["type"] == "citation")["citation"]
    assert citation["type"] == "product"

    # The second request carries the tool result back to the model.
    second = client.messages.requests[1]
    results = second["messages"][-1]["content"]
    assert results[0]["type"] == "tool_result"
    assert "LOOP-1" in json.loads(results[0]["content"])["products"][0]["sku"]


@pytest.mark.anyio
async def test_parallel_tool_results_go_back_in_one_message(
    db_session, company, make_product
):
    """Splitting them across messages trains the model to stop calling in parallel."""
    make_product(company, sku="PAR-1")
    db_session.commit()

    client = FakeClient(
        [
            _turn(
                [
                    _tool_block("search_products", {}, "toolu_a"),
                    _tool_block("warehouse_overview", {}, "toolu_b"),
                ],
                "tool_use",
            ),
            _turn([_text_block("Done.")]),
        ]
    )

    await _collect(client, db_session, company.id)

    final_user_message = client.messages.requests[1]["messages"][-1]
    assert final_user_message["role"] == "user"
    assert len(final_user_message["content"]) == 2


@pytest.mark.anyio
async def test_the_loop_stops_rather_than_calling_tools_forever(db_session, company):
    """A model that never stops asking would otherwise bill indefinitely."""
    client = FakeClient(
        [_turn([_tool_block("warehouse_overview", {})], "tool_use")] * 20
    )

    events = await _collect(client, db_session, company.id)

    assert events[-1]["type"] == "error"
    assert "rounds" in events[-1]["message"]


@pytest.mark.anyio
async def test_a_refusal_is_surfaced_without_reading_empty_content(db_session, company):
    """Refusals return 200 with no text; indexing into content would raise."""
    client = FakeClient([_turn([], "refusal")])

    events = await _collect(client, db_session, company.id)

    assert events[-1]["type"] == "error"
    assert "declined" in events[-1]["message"]


@pytest.mark.anyio
async def test_an_api_failure_becomes_a_readable_message(db_session, company):
    class Exploding:
        class messages:
            @staticmethod
            def stream(**_):
                raise RuntimeError("boom")

    events = await _collect(Exploding(), db_session, company.id)

    assert events[-1]["type"] == "error"
    assert "boom" not in events[-1]["message"]


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
    monkeypatch.setattr(assistant_service.settings, "ANTHROPIC_API_KEY", "")

    response = authenticated_client.post(
        "/api/v1/assistant/ask", json={"question": "how much stock do we have?"}
    )

    assert response.status_code == 200
    assert "ANTHROPIC_API_KEY" in response.text


def test_asking_requires_authentication(client):
    assert (
        client.post("/api/v1/assistant/ask", json={"question": "hi"}).status_code == 401
    )
