"""The assistant: tool scoping, the agentic loop, and what it refuses to do.

No API key and no network. The Gemini client is injected into `converse`, so
a fake returning scripted responses exercises the whole loop -- dispatch, tenant
binding, citation collection, the round cap. The tools are plain functions and
are tested directly.
"""

from types import SimpleNamespace

import pytest

from app.modules.alerts.service import TYPE_LOW_STOCK, AlertService
from app.modules.assistant import redaction
from app.modules.assistant import runtime as runtime_module
from app.modules.assistant import service as assistant_service
from app.modules.assistant import validation
from app.modules.assistant.runtime import LLMResult, LLMRuntime
from app.modules.assistant.tools import TOOLS, run_tool

# ---------------------------------------------------------------------------
# A fake Gemini transport
#
# Only the transport is fake. The parts it yields are real google.genai types,
# because the runtime feeds a model turn straight back into types.Content --
# a SimpleNamespace stand-in would be rejected there, and a fake that cannot
# survive the real code path is not testing the real code path.
#
# The fake no longer calls the tools itself. It says which tools the "model"
# asked for, and the runtime's own dispatch runs them, so the loop under test
# is the one that runs in production.
# ---------------------------------------------------------------------------
from google.genai import types as genai_types  # noqa: E402


def _chunk(parts):
    """One streamed chunk carrying `parts`."""
    return SimpleNamespace(
        candidates=[
            SimpleNamespace(content=SimpleNamespace(parts=parts), finish_reason=None)
        ]
    )


async def _astream(chunks):
    for chunk in chunks:
        yield chunk


class FakeModels:
    """Scripted turns: the planned tool calls first, then the answer."""

    def __init__(self, plan, answer):
        self.plan = list(plan)  # [(tool_name, kwargs), ...] the "model" asks for
        self.answer = answer
        self.requests = []
        self.rounds = 0
        #: Tool results as the model received them -- masked, and carrying any
        #: refusal the budget produced. The fake no longer runs the tools, so
        #: this is how a test sees what a lookup actually returned.
        self.tool_results = []

    async def generate_content_stream(self, model, contents, config):
        self.requests.append({"model": model, "contents": contents, "config": config})
        self._harvest(contents)
        self.rounds += 1
        return _astream(self.turn())

    def _harvest(self, contents):
        for content in contents:
            for part in getattr(content, "parts", None) or []:
                answer = getattr(part, "function_response", None)
                if answer is not None:
                    self.tool_results.append(
                        {"name": answer.name, "response": answer.response}
                    )

    def turn(self):
        """The chunks for this round."""
        if self.rounds == 1 and self.plan:
            return [
                _chunk(
                    [
                        genai_types.Part(
                            function_call=genai_types.FunctionCall(
                                name=name, args=dict(kwargs)
                            )
                        )
                        for name, kwargs in self.plan
                    ]
                )
            ]
        # Answers arrive in pieces, as a real stream does, so tests exercise
        # reassembly rather than a single-fragment special case.
        return [_chunk([genai_types.Part(text=piece)]) for piece in _split(self.answer)]


def _split(text, size=7):
    return [text[i : i + size] for i in range(0, len(text), size)] or []


class FakeClient:
    def __init__(self, plan=(), answer="Here is the answer."):
        self.models = FakeModels(plan, answer)
        self.aio = SimpleNamespace(models=self.models)
        # from_callable() asks the client which API variant it is talking to.
        self.vertexai = False


class ExplodingClient:
    def __init__(self, error):
        async def boom(**_):
            raise error

        self.vertexai = False
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content_stream=boom))


def answer_of(events):
    """The whole answer, reassembled.

    `text` events are fragments now. The browser concatenates them, so a test
    that reads only the first one is testing the transport rather than the
    answer.
    """
    return "".join(e["text"] for e in events if e["type"] == "text")


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

    # Read the declarations the model was actually sent, rather than the
    # Python closures behind them -- the schema is what the model can see and
    # therefore what it could try to supply.
    config = client.models.requests[0]["config"]
    declarations = [d for tool in config.tools for d in tool.function_declarations]
    assert declarations, "the model was sent no tools at all"
    for declaration in declarations:
        properties = getattr(declaration.parameters, "properties", None) or {}
        assert "company_id" not in properties
        assert "db" not in properties

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


def test_several_alerts_produce_several_distinct_citations(
    db_session, company, make_product, make_warehouse, make_stock
):
    """The regression that motivated the fix.

    De-duplication keys on a citation's `ref`, so `ref` has to identify the
    RECORD. The arguments to `_cite` were once transposed, which put the
    severity in that slot -- and since every low-stock alert is a "warning",
    three separate alerts collapsed into one citation reading "warning". The
    answer named three products and the evidence panel showed a single word.
    """
    warehouse = make_warehouse(company)
    alerts = AlertService(db_session)
    for sku in ("ALERT-A", "ALERT-B", "ALERT-C"):
        stock = make_stock(make_product(company, sku=sku), warehouse, quantity=1)
        alerts.open_alert(
            company_id=company.id,
            alert_type=TYPE_LOW_STOCK,
            severity="warning",  # identical on purpose: the collapsing value
            subject_type="inventory",
            subject_id=stock.id,
            title=f"{sku} is below its reorder point",
            detail={"quantity": 1, "reorder_point": 20},
        )
    db_session.commit()

    _, citations = run_tool(db_session, company.id, "list_alerts", {})

    refs = [c["ref"] for c in citations]
    assert len(set(refs)) == 3, f"three alerts collapsed into {set(refs)}"
    assert "warning" not in refs


@pytest.mark.anyio
async def test_distinct_alerts_survive_de_duplication_through_the_loop(
    db_session, company, make_product, make_warehouse, make_stock
):
    """The same property, asserted end to end -- de-duplication happens in
    `converse`, so the tool-level test above cannot prove what reaches the UI."""
    warehouse = make_warehouse(company)
    alerts = AlertService(db_session)
    for sku in ("LOOP-A", "LOOP-B"):
        stock = make_stock(make_product(company, sku=sku), warehouse, quantity=1)
        alerts.open_alert(
            company_id=company.id,
            alert_type=TYPE_LOW_STOCK,
            severity="critical",
            subject_type="inventory",
            subject_id=stock.id,
            title=f"{sku} is below its reorder point",
            detail={"quantity": 1, "reorder_point": 20},
        )
    db_session.commit()

    client = FakeClient(plan=[("list_alerts", {})], answer="Two things need attention.")
    events = await _collect(client, db_session, company.id)

    refs = [e["citation"]["ref"] for e in events if e["type"] == "citation"]
    assert len(refs) == len(set(refs)) == 2


# ---------------------------------------------------------------------------
# The tool-call budget
#
# The cap lives inside the tools rather than around the loop, because the SDK
# owns the loop. These tests exist because the cap was silently LOST in the move
# from Anthropic (where the loop was ours, and had MAX_ROUNDS) to Gemini.
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_a_runaway_model_is_capped(
    db_session, company, make_product, monkeypatch
):
    monkeypatch.setattr(assistant_service.settings, "MAX_TOOL_CALLS", 3)
    make_product(company, sku="CAP-1")
    db_session.commit()

    # A model that will not stop calling tools.
    client = FakeClient(
        plan=[("search_products", {})] * 10,
        answer="I found what I could.",
    )
    events = await _collect(client, db_session, company.id)

    tools_run = [e for e in events if e["type"] == "tool"]
    assert len(tools_run) == 3, "the budget did not stop the loop"

    notice = next(e for e in events if e["type"] == "notice")
    assert "3 lookups" in notice["message"]
    assert events[-1]["truncated"] is True


@pytest.mark.anyio
async def test_the_refusal_is_readable_by_the_model(db_session, company, monkeypatch):
    """Over budget returns an explanation, not an exception.

    Raising would abort the turn and throw away the results already gathered.
    Returning a message the model can read lets it answer from what it has --
    which is the difference between a degraded answer and no answer.
    """
    monkeypatch.setattr(assistant_service.settings, "MAX_TOOL_CALLS", 1)

    captured = []

    # Two lookups in one turn, against a budget of one. The runtime dispatches
    # both, so the second must come back as a refusal the model can read.
    client = FakeClient(
        plan=[("warehouse_overview", {}), ("warehouse_overview", {})],
        answer="Answered anyway.",
    )

    events = await _collect(client, db_session, company.id)
    captured = [result["response"] for result in client.models.tool_results]

    assert len(captured) == 2
    assert "error" not in captured[0]
    assert captured[1]["error"] == "tool_budget_exceeded"
    assert "answer from the results you have" in captured[1]["message"].lower()
    assert answer_of(events) == "Answered anyway."


@pytest.mark.anyio
async def test_a_capped_search_with_no_answer_blames_the_cap_not_the_question(
    db_session, company, monkeypatch
):
    monkeypatch.setattr(assistant_service.settings, "MAX_TOOL_CALLS", 1)

    client = FakeClient(plan=[("warehouse_overview", {})] * 4, answer="")
    events = await _collect(client, db_session, company.id)

    assert events[-1]["type"] == "error"
    assert "more lookups" in events[-1]["message"]


@pytest.mark.anyio
async def test_a_normal_question_is_not_flagged_as_truncated(
    db_session, company, make_product
):
    make_product(company, sku="FINE-1")
    db_session.commit()

    client = FakeClient(plan=[("search_products", {})], answer="One product.")
    events = await _collect(client, db_session, company.id)

    assert events[-1]["truncated"] is False
    assert not any(e["type"] == "notice" for e in events)


# ---------------------------------------------------------------------------
# Demo privacy mode
# ---------------------------------------------------------------------------
def test_demo_mode_masks_identifiers_without_destroying_meaning(monkeypatch):
    monkeypatch.setattr(redaction.settings, "LLM_DATA_MODE", "demo")

    payload = {
        "products": [
            {"sku": "WIDGET-9", "name": "Blue widget", "quantity": 12},
            {"sku": "WIDGET-9", "name": "Blue widget", "quantity": 3},
            {"sku": "GADGET-2", "name": "Red gadget", "quantity": 7},
        ]
    }

    masked = redaction.redact(payload)
    skus = [p["sku"] for p in masked["products"]]

    # Gone...
    assert "WIDGET-9" not in skus
    # ...but the same product is still recognisably the same product, and a
    # different one is still different. Without that the model cannot connect
    # "the item that is low" to "the item you asked about".
    assert skus[0] == skus[1] != skus[2]
    # And everything the answer is actually made of survives untouched.
    assert masked["products"][0]["quantity"] == 12
    assert masked["products"][0]["name"] == "Blue widget"


def test_production_mode_changes_nothing(monkeypatch):
    monkeypatch.setattr(redaction.settings, "LLM_DATA_MODE", "production")
    payload = {"products": [{"sku": "WIDGET-9"}]}

    assert redaction.redact(payload) is payload


def test_an_unrecognised_mode_fails_closed(monkeypatch):
    """A typo in LLM_DATA_MODE must not silently start sending real data."""
    monkeypatch.setattr(redaction.settings, "LLM_DATA_MODE", "prod")

    assert redaction.is_demo_mode() is True


@pytest.mark.anyio
async def test_citations_keep_the_real_sku_while_the_model_sees_a_pseudonym(
    db_session, company, make_product, monkeypatch
):
    """The point of the whole design.

    The model reasons over pseudonyms; the user reads real records. If masking
    reached the citations, the evidence panel would be a list of hashes and the
    feature would be worthless.
    """
    monkeypatch.setattr(redaction.settings, "LLM_DATA_MODE", "demo")
    make_product(company, sku="REAL-SKU-1", name="Real widget")
    db_session.commit()

    seen = {}

    client = FakeClient(
        plan=[("search_products", {"query": "Real"})], answer="Found it."
    )

    events = await _collect(client, db_session, company.id)

    seen["payload"] = client.models.tool_results[0]["response"]
    model_saw = [p["sku"] for p in seen["payload"]["products"]]
    assert "REAL-SKU-1" not in model_saw

    refs = [e["citation"]["ref"] for e in events if e["type"] == "citation"]
    assert "REAL-SKU-1" in refs


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


# ---------------------------------------------------------------------------
# The provider boundary
#
# The value of LLMRuntime is that everything above it survives a change of
# vendor. These tests assert that by driving the whole loop through a runtime
# that is not Gemini and has never heard of it.
# ---------------------------------------------------------------------------
class FakeRuntime(LLMRuntime):
    """A provider that is not Gemini, to prove nothing above depends on Gemini."""

    name = "fake"

    def __init__(self, plan=(), answer="Answered."):
        self.plan = list(plan)
        self.answer = answer
        self.seen = {}

    @property
    def model(self):
        return "fake-model-1"

    @staticmethod
    def is_configured():
        return True

    async def generate(self, *, system_prompt, history, question, tools):
        self.seen = {"system_prompt": system_prompt, "history": history, "tools": tools}
        by_name = {t.__name__: t for t in tools}
        for name, kwargs in self.plan:
            by_name[name](**kwargs)
        return LLMResult(text=self.answer, latency_ms=1.0)

    def describe_error(self, error):
        return "fake failure"


@pytest.mark.anyio
async def test_the_loop_runs_on_a_provider_that_is_not_gemini(
    db_session, company, make_product
):
    make_product(company, sku="PORTABLE-1", name="Portable widget")
    db_session.commit()

    runtime = FakeRuntime(plan=[("search_products", {"query": "Portable"})])
    events = [
        e
        async for e in assistant_service.converse(
            runtime=runtime, db=db_session, company_id=company.id, question="what?"
        )
    ]

    assert next(e for e in events if e["type"] == "text")["text"] == "Answered."
    assert next(e for e in events if e["type"] == "citation")["citation"]["ref"] == (
        "PORTABLE-1"
    )
    # And the safety properties still hold, on a provider that knows none of them.
    for tool in runtime.seen["tools"]:
        assert "company_id" not in tool.__code__.co_varnames


@pytest.mark.anyio
async def test_a_provider_failure_becomes_a_sentence_not_an_exception(
    db_session, company
):
    class Failing(FakeRuntime):
        async def generate(self, **_):
            return LLMResult(error="The provider is down.", latency_ms=2.0)

    events = [
        e
        async for e in assistant_service.converse(
            runtime=Failing(), db=db_session, company_id=company.id, question="hi"
        )
    ]

    assert events == [{"type": "error", "message": "The provider is down."}]


def test_an_unknown_provider_falls_back_rather_than_going_offline(monkeypatch):
    """A typo in one variable should not take the assistant down."""
    monkeypatch.setattr(runtime_module.settings, "LLM_PROVIDER", "gpt-9")

    assert runtime_module.get_runtime().name == "gemini"


def test_gemini_error_advice_lives_with_gemini():
    """Error wording is provider-specific, so it belongs in the provider."""
    gemini = runtime_module.GeminiRuntime()

    assert "GEMINI_API_KEY" in gemini.describe_error(
        RuntimeError("401 UNAUTHENTICATED")
    )
    assert "rate limit" in gemini.describe_error(RuntimeError("429 quota")).lower()


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------
def test_a_claim_of_having_acted_is_flagged():
    """The assistant cannot write. A confident claim that it did is the failure
    most likely to cause real damage, because it stops someone from checking."""
    result = validation.validate_answer(
        "I have placed the purchase order for 40 units of WIDGET-9."
    )

    assert "claimed_action" in result.flags
    assert result.warnings and "cannot change anything" in result.warnings[0]
    # The text is annotated, not deleted -- hiding it would hide the misbehaviour.
    assert "purchase order" in result.text


def test_reporting_an_action_someone_else_took_is_not_flagged():
    """`list_alerts` legitimately returns "the order was placed on Tuesday"."""
    result = validation.validate_answer(
        "The order was placed on Tuesday and stock was updated overnight."
    )

    assert result.clean


def test_a_leaked_key_never_reaches_the_screen():
    result = validation.validate_answer(
        "Your configured key is sk-ant-api03-AbCdEfGhIjKlMnOpQrSt and it works."
    )

    assert "secret_redacted" in result.flags
    assert "sk-ant" not in result.text
    assert "[redacted]" in result.text


def test_a_runaway_generation_is_cut_and_says_so():
    result = validation.validate_answer("word " * 4000)

    assert "truncated" in result.flags
    assert len(result.text) <= validation.MAX_ANSWER_CHARS
    assert any("cut short" in w for w in result.warnings)


def test_an_ordinary_answer_passes_untouched():
    text = "You have 9,199 units across 4 warehouses. Two lines need reordering."

    result = validation.validate_answer(text)

    assert result.clean and result.text == text


@pytest.mark.anyio
async def test_validation_runs_before_anything_reaches_the_client(db_session, company):
    events = [
        e
        async for e in assistant_service.converse(
            runtime=FakeRuntime(answer="I have updated the stock levels for you."),
            db=db_session,
            company_id=company.id,
            question="fix it",
        )
    ]

    notice = next(e for e in events if e["type"] == "notice")
    assert "cannot change anything" in notice["message"]
    assert "claimed_action" in events[-1]["flags"]


@pytest.mark.anyio
async def test_the_answer_speaks_in_real_skus_even_though_the_model_did_not(
    db_session, company, make_product, monkeypatch
):
    """The round trip: masked outbound, restored inbound.

    Without this the demo-mode answer would read "SKU-3F9A11 is low", which is
    an unusable product even though it is a private one.
    """
    monkeypatch.setattr(redaction.settings, "LLM_DATA_MODE", "demo")
    make_product(company, sku="ROUNDTRIP-1", name="Round widget")
    db_session.commit()

    token = redaction.pseudonym("ROUNDTRIP-1")

    runtime = FakeRuntime(
        plan=[("search_products", {})],
        answer=f"{token} is the one to watch.",
    )
    events = [
        e
        async for e in assistant_service.converse(
            runtime=runtime, db=db_session, company_id=company.id, question="which?"
        )
    ]

    assert answer_of(events) == "ROUNDTRIP-1 is the one to watch."


@pytest.mark.anyio
async def test_a_pseudonym_the_model_invented_is_left_alone(
    db_session, company, monkeypatch
):
    """Only tokens actually issued are restored. Inventing a mapping for a
    hallucinated one would turn an obvious error into a convincing one."""
    monkeypatch.setattr(redaction.settings, "LLM_DATA_MODE", "demo")

    events = [
        e
        async for e in assistant_service.converse(
            runtime=FakeRuntime(answer="SKU-ZZZZZZ is low."),
            db=db_session,
            company_id=company.id,
            question="which?",
        )
    ]

    assert answer_of(events) == "SKU-ZZZZZZ is low."


# ---------------------------------------------------------------------------
# The streamed loop
#
# These cover what changed when the runtime took the tool loop back from the
# SDK: progress that arrives while the model is still working, an answer that
# arrives in pieces, and the one detail that makes a hand-written loop work at
# all on a Gemini 3 model.
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_lookups_are_reported_before_the_answer_not_after(db_session, company):
    """The whole point of owning the loop.

    Tool events used to be emitted after the answer was complete, which is the
    one moment they are of no use: the reader had already finished reading. A
    lookup has to be announced while it is the reason for the wait.
    """
    client = FakeClient(plan=[("warehouse_overview", {})], answer="Two sites.")

    events = await _collect(client, db_session, company.id)
    kinds = [e["type"] for e in events]

    assert "tool" in kinds and "text" in kinds
    assert kinds.index("tool") < kinds.index("text")


@pytest.mark.anyio
async def test_the_answer_arrives_in_pieces(db_session, company):
    """Streaming is only streaming if more than one fragment reaches the client."""
    client = FakeClient(plan=[], answer="A reasonably long answer to split up.")

    events = await _collect(client, db_session, company.id)

    fragments = [e for e in events if e["type"] == "text"]
    assert len(fragments) > 1
    assert answer_of(events) == "A reasonably long answer to split up."


@pytest.mark.anyio
async def test_private_reasoning_never_reaches_the_reader(db_session, company):
    """A thought part is the model talking to itself.

    It is echoed back to the provider, because dropping it breaks the turn, but
    it is not the answer and it can quote tool results verbatim -- including
    rows the redactor masked on the way out.
    """

    class Thinking(FakeModels):
        def turn(self):
            return [
                _chunk(
                    [
                        genai_types.Part(
                            text="The user wants stock. I should check.",
                            thought=True,
                        ),
                        genai_types.Part(text="Two sites."),
                    ]
                )
            ]

    client = FakeClient()
    client.models = Thinking([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert answer_of(events) == "Two sites."
    assert "I should check" not in answer_of(events)


@pytest.mark.anyio
async def test_the_model_turn_is_echoed_back_verbatim(db_session, company):
    """The line that makes a hand-written loop work.

    Gemini 3 carries a thought_signature through a turn. Rebuilding the model's
    turn from the function calls we read out of it -- which is the obvious way
    to write this -- drops the signature, and a model that loses it re-issues
    the same tool call instead of answering. So the parts go back exactly as
    they arrived.
    """
    signed = genai_types.Part(
        function_call=genai_types.FunctionCall(name="warehouse_overview", args={}),
        thought_signature=b"opaque-signature",
    )

    class Signed(FakeModels):
        def turn(self):
            if self.rounds == 1:
                return [_chunk([signed])]
            return [_chunk([genai_types.Part(text="Two sites.")])]

    client = FakeClient()
    client.models = Signed([], "")
    client.aio = SimpleNamespace(models=client.models)

    await _collect(client, db_session, company.id)

    # The second request must carry the signature the first one produced.
    replayed = [
        part
        for content in client.models.requests[1]["contents"]
        for part in (getattr(content, "parts", None) or [])
        if getattr(part, "thought_signature", None)
    ]
    assert replayed, "the model turn was rebuilt instead of echoed"
    assert replayed[0].thought_signature == b"opaque-signature"


@pytest.mark.anyio
async def test_a_rate_limit_is_waited_out_rather_than_shown(
    db_session, company, monkeypatch
):
    """A 429 on a free-tier key is a wait, not a failure.

    Retried only before any text has been shown -- restarting a turn the reader
    is already watching would print the answer twice.
    """
    monkeypatch.setattr(runtime_module.asyncio, "sleep", _no_wait)
    attempts = {"n": 0}

    class Limited(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")
            return _astream([_chunk([genai_types.Part(text="Two sites.")])])

    client = FakeClient()
    client.models = Limited([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert attempts["n"] == 2
    assert answer_of(events) == "Two sites."
    assert not [e for e in events if e["type"] == "error"]


@pytest.mark.anyio
async def test_a_model_that_never_answers_is_stopped(db_session, company, monkeypatch):
    """Bounded in round trips, not only in lookups.

    MAX_TOOL_CALLS caps lookups, but a model looping on a tool it is refused
    would still keep the request open. ASSISTANT_MAX_ROUNDS ends it.
    """
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MAX_ROUNDS", 3)

    class Looping(FakeModels):
        def turn(self):
            return [
                _chunk(
                    [
                        genai_types.Part(
                            function_call=genai_types.FunctionCall(
                                name="warehouse_overview", args={}
                            )
                        )
                    ]
                )
            ]

    client = FakeClient()
    client.models = Looping([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert client.models.rounds == 3
    assert events[-1]["type"] == "error"


@pytest.mark.anyio
async def test_a_tool_the_model_invented_is_answered_not_crashed(db_session, company):
    """An unknown tool name is a correctable mistake, not a 500."""

    class Inventing(FakeModels):
        def turn(self):
            if self.rounds == 1:
                return [
                    _chunk(
                        [
                            genai_types.Part(
                                function_call=genai_types.FunctionCall(
                                    name="delete_everything", args={}
                                )
                            )
                        ]
                    )
                ]
            return [_chunk([genai_types.Part(text="I cannot do that.")])]

    client = FakeClient()
    client.models = Inventing([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert client.models.tool_results[0]["response"]["error"] == "unknown_tool"
    assert answer_of(events) == "I cannot do that."


async def _no_wait(_seconds):
    return None
