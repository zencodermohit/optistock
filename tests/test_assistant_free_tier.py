"""Getting a useful assistant out of a free-tier key.

The Gemini free tier allows a fixed number of requests per model per day. That
number is small enough that the interesting question stops being "how fast" and
becomes "how many questions can this answer at all", which these two features
exist to improve:

*   the daily cap is per MODEL, so a chain of models multiplies the allowance;
*   a repeat question answered from cache spends nothing.

The tests worth having here are the ones about what must NOT happen: waiting out
a cap that will not clear, handing one model another's thought signatures, and
replaying an answer that claimed to have done something.
"""

import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from google.genai import types as genai_types

from app.modules.assistant import cache as answer_cache
from app.modules.assistant import runtime as runtime_module
from app.modules.assistant import service as assistant_service

from tests.test_assistant import (  # noqa: F401 -- fixtures come via conftest
    FakeClient,
    FakeModels,
    _astream,
    _chunk,
    _collect,
    answer_of,
)

PER_DAY = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded "
    "your current quota'}, 'details': [{'@type': 'type.googleapis.com/"
    "google.rpc.QuotaFailure', 'violations': [{'quotaMetric': "
    "'generativelanguage.googleapis.com/generate_content_free_tier_requests', "
    "'quotaId': 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'}]}]}"
)
PER_MINUTE = (
    "429 RESOURCE_EXHAUSTED. {'error': {'code': 429}, 'details': [{'quotaId': "
    "'GenerateRequestsPerMinutePerProjectPerModel-FreeTier'}]}"
)


@pytest.fixture(autouse=True)
def _clean():
    runtime_module.reset_cooldowns()
    answer_cache.clear_answers()
    yield
    runtime_module.reset_cooldowns()
    answer_cache.clear_answers()


async def _no_wait(_seconds):
    return None


# ---------------------------------------------------------------------------
# Telling the two 429s apart
# ---------------------------------------------------------------------------
def test_the_two_quota_failures_are_not_the_same_problem():
    """They share a status code and need opposite responses: one is waited
    out, the other never clears while anyone is waiting."""
    assert runtime_module._quota_scope(RuntimeError(PER_DAY)) == "day"
    assert runtime_module._quota_scope(RuntimeError(PER_MINUTE)) == "minute"
    assert runtime_module._quota_scope(RuntimeError("429 too many")) == "minute"
    assert runtime_module._quota_scope(RuntimeError("500 internal")) is None
    assert runtime_module._quota_scope(RuntimeError("401 bad key")) is None


@pytest.mark.anyio
async def test_a_daily_cap_is_not_waited_out(monkeypatch, db_session, company):
    """The failure mode this replaces. The old code retried any 429, which on
    a per-day cap spends the retry budget sleeping through something that will
    not clear until tomorrow -- and makes the person watch it happen."""
    slept = []

    async def record(seconds):
        slept.append(seconds)

    monkeypatch.setattr(runtime_module.asyncio, "sleep", record)
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "")
    asked = []

    class Capped(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            asked.append(model)
            raise RuntimeError(PER_DAY)

    client = FakeClient()
    client.models = Capped([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert slept == [], "waited out a cap that does not clear by waiting"
    assert len(asked) == 1, "asked twice for something already refused for the day"
    assert [e for e in events if e["type"] == "error"]


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_a_model_out_for_the_day_hands_over_to_the_next(
    db_session, company, monkeypatch
):
    """The whole point of a chain. The daily cap is per model, so a refusal
    from one says nothing about the next."""
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(
        runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup, spare"
    )
    monkeypatch.setattr(assistant_service.settings, "ASSISTANT_MODEL", "primary")
    tried = []

    class Chained(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            if model == "primary":
                raise RuntimeError(PER_DAY)
            return _astream([_chunk([genai_types.Part(text="Two sites.")])])

    client = FakeClient()
    client.models = Chained([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert tried == ["primary", "backup"]
    assert answer_of(events) == "Two sites."
    # And the reader is told, so a different-sounding answer has a reason.
    notices = [e["message"] for e in events if e["type"] == "notice"]
    assert any("backup" in n and "free quota" in n for n in notices)


@pytest.mark.anyio
async def test_an_exhausted_model_is_not_tried_again_for_every_question(
    db_session, company, monkeypatch
):
    """A wasted request matters when the daily allowance is twenty. Once a
    model has said it is out for the day, it is skipped rather than re-probed
    on the next question."""
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup")
    tried = []

    class Chained(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            if model == "primary":
                raise RuntimeError(PER_DAY)
            return _astream([_chunk([genai_types.Part(text="ok")])])

    # Three DIFFERENT questions, or the answer cache answers the last two and
    # this measures nothing. (It did, the first time this was written.)
    for n in range(3):
        client = FakeClient()
        client.models = Chained([], "")
        client.aio = SimpleNamespace(models=client.models)
        await _collect(client, db_session, company.id, question=f"question {n}")

    # Refused once, then skipped -- not asked three times.
    assert tried.count("primary") == 1
    assert tried.count("backup") == 3


@pytest.mark.anyio
async def test_the_cooldown_expires_so_a_model_cannot_be_lost_forever(
    db_session, company, monkeypatch
):
    """The cooldown is a guess about when Google resets a quota, in a timezone
    that is not ours. A guess that never expires would retire a working model
    permanently."""
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL_COOLDOWN_SECONDS", 0)

    runtime_module._rest("primary")
    assert "primary" in runtime_module._COOLDOWN
    time.sleep(0.01)
    assert runtime_module.GeminiRuntime()._usable()[0] == "primary"


@pytest.mark.anyio
async def test_with_every_model_out_the_error_says_so(db_session, company, monkeypatch):
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup")

    class AllOut(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            raise RuntimeError(PER_DAY)

    client = FakeClient()
    client.models = AllOut([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)
    error = [e for e in events if e["type"] == "error"]
    assert error and "today" in error[0]["message"]
    assert "billing" in error[0]["message"] or "ASSISTANT_MODEL" in error[0]["message"]


@pytest.mark.anyio
async def test_a_per_minute_cap_still_waits_on_the_same_model(
    db_session, company, monkeypatch
):
    """Switching model on a per-minute cap would spend a second model's daily
    allowance to avoid a two second wait."""
    monkeypatch.setattr(runtime_module.asyncio, "sleep", _no_wait)
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup")
    tried = []

    class Busy(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            if len(tried) == 1:
                raise RuntimeError(PER_MINUTE)
            return _astream([_chunk([genai_types.Part(text="ok")])])

    client = FakeClient()
    client.models = Busy([], "")
    client.aio = SimpleNamespace(models=client.models)

    await _collect(client, db_session, company.id)
    assert tried == ["primary", "primary"]


@pytest.mark.anyio
async def test_the_model_is_not_swapped_once_a_turn_is_under_way(
    db_session, company, monkeypatch
):
    """Contents by round two carry thought signatures belonging to the model
    that produced them. Handing those to a different model is not something to
    discover in production."""
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup")
    tried = []

    class LateCap(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            if len(tried) == 1:
                return _astream(
                    [
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
                )
            raise RuntimeError(PER_DAY)

    client = FakeClient()
    client.models = LateCap([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert tried == ["primary", "primary"], "a mid-turn round must not switch model"
    assert [e for e in events if e["type"] == "error"]


# ---------------------------------------------------------------------------
# The answer cache
# ---------------------------------------------------------------------------
@pytest.mark.anyio
async def test_a_repeat_question_spends_no_request(db_session, company):
    client = FakeClient(plan=[("warehouse_overview", {})], answer="Two sites.")
    first = await _collect(client, db_session, company.id, question="How many sites?")
    calls_after_first = client.models.rounds

    again = FakeClient(plan=[], answer="SHOULD NOT BE ASKED")
    second = await _collect(again, db_session, company.id, question="How many sites?")

    assert calls_after_first > 0
    assert again.models.rounds == 0, "the model was asked despite a cached answer"
    assert answer_of(second) == answer_of(first) == "Two sites."
    assert second[-1]["type"] == "done" and second[-1]["cached"] is True


@pytest.mark.anyio
async def test_the_cache_cannot_serve_another_tenant(db_session, company):
    """The same rule the tool cache follows, for the same reason, and this is
    the test to read first if either is ever refactored."""
    client = FakeClient(plan=[], answer="Ours.")
    await _collect(client, db_session, company.id, question="what is low?")

    other = uuid4()
    assert answer_cache.answer_for(other, "what is low?", False) is None
    assert answer_cache.answer_for(company.id, "what is low?", False) is not None


@pytest.mark.anyio
async def test_a_follow_up_is_never_served_from_cache(db_session, company):
    """ "And the other warehouse?" means whatever the previous turn said, so it
    has no answer of its own to store or to replay."""
    client = FakeClient(plan=[], answer="Mumbai.")
    events = [
        e
        async for e in assistant_service.converse(
            client=client,
            db=db_session,
            company_id=company.id,
            question="which site?",
            history=[{"role": "user", "text": "earlier"}],
        )
    ]
    assert answer_of(events) == "Mumbai."
    assert answer_cache.answer_for(company.id, "which site?", False) is None


@pytest.mark.anyio
async def test_an_answer_that_proposed_an_order_is_never_replayed(
    db_session, company, make_product
):
    """The important one. "It is waiting for your approval" is true the first
    time and false every time after, because replaying it proposes nothing --
    the reader would be told an order exists that does not."""
    make_product(company, sku="CACHE-1", name="Cacheable widget")
    db_session.commit()

    client = FakeClient(
        plan=[("create_purchase_order", {"sku": "CACHE-1", "quantity": 5})],
        answer="Done - it is waiting for your approval.",
    )
    await _collect(client, db_session, company.id, question="reorder CACHE-1")

    assert answer_cache.answer_for(company.id, "reorder CACHE-1", False) is None


@pytest.mark.anyio
async def test_a_flagged_answer_is_not_kept(db_session, company):
    """Anything the output filter had to annotate is not worth repeating."""
    client = FakeClient(plan=[], answer="I have updated the stock levels.")
    events = await _collect(client, db_session, company.id, question="fix it")

    assert [e for e in events if e["type"] == "notice"]
    assert answer_cache.answer_for(company.id, "fix it", False) is None


@pytest.mark.anyio
async def test_wording_that_differs_only_in_spacing_is_one_entry(db_session, company):
    client = FakeClient(plan=[], answer="Four.")
    await _collect(client, db_session, company.id, question="How many  sites?")

    assert answer_cache.answer_for(company.id, "how many sites?", False) is not None
    assert answer_cache.answer_for(company.id, "how many warehouses?", False) is None


@pytest.mark.anyio
async def test_the_cache_can_be_switched_off(db_session, company, monkeypatch):
    monkeypatch.setattr(answer_cache.settings, "ANSWER_CACHE_TTL_SECONDS", 0)
    client = FakeClient(plan=[], answer="Four.")
    await _collect(client, db_session, company.id, question="how many?")
    assert answer_cache.answer_for(company.id, "how many?", False) is None


@pytest.mark.anyio
async def test_a_retired_model_hands_over_instead_of_killing_the_feature(
    db_session, company, monkeypatch
):
    """Google withdraws models -- the 2.5 Flash family already 404s on a key
    that could reach it before. Without a fallback, the day the primary is
    retired the assistant stops answering, one line away from carrying on with
    the next model in its own chain."""
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "withdrawn")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "current")
    tried = []

    class Retired(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            if model == "withdrawn":
                raise RuntimeError(
                    "404 NOT_FOUND. models/withdrawn is not found for API version v1beta"
                )
            return _astream([_chunk([genai_types.Part(text="Still here.")])])

    client = FakeClient()
    client.models = Retired([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert tried == ["withdrawn", "current"]
    assert answer_of(events) == "Still here."


@pytest.mark.anyio
async def test_with_no_model_left_the_advice_is_still_the_right_advice(
    db_session, company, monkeypatch
):
    """The fallback must not swallow a misconfiguration. If nothing works, the
    message still names the setting to fix."""
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "typo")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "typo2")

    class NoneWork(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            raise RuntimeError("404 NOT_FOUND. not found for API version v1beta")

    client = FakeClient()
    client.models = NoneWork([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)
    error = [e for e in events if e["type"] == "error"]
    assert error and "ASSISTANT_MODEL" in error[0]["message"]


@pytest.mark.anyio
async def test_a_busy_fallback_does_not_abort_the_whole_chain(
    db_session, company, monkeypatch
):
    """Found against the live API rather than reasoned about.

    A per-minute limit is retried on the same model, which is right. But when
    the retries ran out the code raised, and raising in the middle of a chain
    throws away every model still untried. A per-minute cap is per model too,
    so the next one is very likely to answer immediately."""
    monkeypatch.setattr(runtime_module.asyncio, "sleep", _no_wait)
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(
        runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "busy,quiet"
    )
    tried = []

    class Busy(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            if model == "primary":
                raise RuntimeError(PER_DAY)
            if model == "busy":
                raise RuntimeError(PER_MINUTE)
            return _astream([_chunk([genai_types.Part(text="Answered.")])])

    client = FakeClient()
    client.models = Busy([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert answer_of(events) == "Answered."
    assert tried[0] == "primary" and tried[-1] == "quiet"
    # Busy was retried on itself before being passed over, not skipped outright.
    assert tried.count("busy") > 1
    # ...and not put to rest for an hour: it has allowance left, it is just busy.
    assert "busy" not in runtime_module._COOLDOWN
    assert "primary" in runtime_module._COOLDOWN


@pytest.mark.anyio
async def test_an_error_that_is_not_about_the_model_stops_immediately(
    db_session, company, monkeypatch
):
    """A rejected key fails the same way on every model. Walking the chain
    would turn one clear error into four identical ones and a slower failure."""
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup")
    tried = []

    class BadKey(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            raise RuntimeError("401 UNAUTHENTICATED: API key not valid")

    client = FakeClient()
    client.models = BadKey([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert tried == ["primary"]
    assert "GEMINI_API_KEY" in [e for e in events if e["type"] == "error"][0]["message"]


# ---------------------------------------------------------------------------
# Where the request actually happens
# ---------------------------------------------------------------------------
async def _raises_on_iteration(error):
    """A stream that behaves the way the real SDK does.

    `await generate_content_stream(...)` sends nothing. The SDK defers the
    request to the first iteration, so an error arrives while the caller is
    reading chunks rather than while it is opening the stream. Every fake above
    raises from the call instead, which is convenient and wrong in exactly the
    way that let a retry pass its tests while never running in production.
    """
    raise error
    yield  # pragma: no cover -- makes this an async generator


@pytest.mark.anyio
async def test_a_failure_raised_on_the_first_chunk_is_still_handled(
    db_session, company, monkeypatch
):
    """The regression test for a bug that shipped.

    The daily cap, the per-minute retry and the chain all sat around a call
    that cannot fail, so none of them ever ran against the real API. They only
    work if a chunk is pulled while the handler is still watching.
    """
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_MODEL", "primary")
    monkeypatch.setattr(runtime_module.settings, "ASSISTANT_FALLBACK_MODELS", "backup")
    tried = []

    class Deferred(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            tried.append(model)
            if model == "primary":
                # Opening succeeds. Reading is what fails -- as it does for real.
                return _raises_on_iteration(RuntimeError(PER_DAY))
            return _astream([_chunk([genai_types.Part(text="Carried on.")])])

    client = FakeClient()
    client.models = Deferred([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)

    assert tried == ["primary", "backup"], "a deferred failure bypassed the chain"
    assert answer_of(events) == "Carried on."
    assert "primary" in runtime_module._COOLDOWN


@pytest.mark.anyio
async def test_a_stream_that_ends_with_nothing_in_it_is_not_a_crash(
    db_session, company
):
    """Pulling a chunk early has to cope with there being none to pull."""

    class Empty(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            return _astream([])

    client = FakeClient()
    client.models = Empty([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)
    assert events[-1]["type"] == "error"
    assert "no answer" in events[-1]["message"]


@pytest.mark.anyio
async def test_no_chunk_is_swallowed_by_being_pulled_early(db_session, company):
    """The chunk taken to trigger the request must be put back, or every
    answer loses its first fragment."""

    class Several(FakeModels):
        async def generate_content_stream(self, model, contents, config):
            return _astream(
                [
                    _chunk([genai_types.Part(text="First ")]),
                    _chunk([genai_types.Part(text="second ")]),
                    _chunk([genai_types.Part(text="third.")]),
                ]
            )

    client = FakeClient()
    client.models = Several([], "")
    client.aio = SimpleNamespace(models=client.models)

    events = await _collect(client, db_session, company.id)
    assert answer_of(events) == "First second third."
