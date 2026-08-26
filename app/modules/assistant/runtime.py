"""The provider boundary.

Everything that knows a particular vendor's SDK exists below this line;
everything above it -- tenant binding, the tool budget, redaction, validation,
citations -- is ours and stays put when the vendor changes.

That is not a hypothetical. This project has already moved once, from Anthropic
to Gemini, and the move touched the loop, the error strings, the tests and the
tool declarations because none of it was separated. This module is the lesson
from that migration written down: a second move should be one new subclass.

The interface is deliberately narrow. A runtime is handed a system prompt, a
conversation, and a list of plain Python functions, and produces an answer. How
it gets there -- whether the SDK runs the tool loop or the runtime runs it by
hand -- is the runtime's business.

    tools as Python callables      Gemini derives its schemas by introspection.
                                   A provider needing JSON declarations can
                                   read app.modules.assistant.tools.TOOLS and
                                   dispatch by __name__; the callables carry
                                   the tenant binding either way, which is the
                                   property that must not vary by provider.

There are two entry points, and `stream` is the real one. `generate` is defined
in terms of it so there is exactly one code path -- a provider integration with
two of them grows a bug in whichever one the tests do not cover.
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Sequence

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    """One completed turn, in provider-neutral terms."""

    text: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None
    #: Provider-specific extras worth logging but never worth branching on.
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


class LLMRuntime(ABC):
    """One model provider, reduced to the things the app needs from it."""

    #: Short identifier, logged and published on /status.
    name: str = "unknown"

    @property
    def model(self) -> str:
        return settings.ASSISTANT_MODEL

    @staticmethod
    @abstractmethod
    def is_configured() -> bool:
        """Whether this runtime has what it needs to run at all."""

    @abstractmethod
    async def generate(
        self,
        *,
        system_prompt: str,
        history: Sequence[Dict[str, Any]],
        question: str,
        tools: List[Callable[..., dict]],
    ) -> LLMResult:
        """Answer one question, calling tools as needed.

        Must not raise for provider failures -- return an LLMResult carrying a
        human-readable `error` instead. The caller streams to a browser, where
        an exception is a blank screen and a sentence is an explanation.
        """

    async def stream(
        self,
        *,
        system_prompt: str,
        history: Sequence[Dict[str, Any]],
        question: str,
        tools: List[Callable[..., dict]],
    ) -> AsyncIterator[Dict[str, Any]]:
        """Answer one question, yielding progress as it happens.

            {"type": "text",      "text": ...}   a fragment of the answer
            {"type": "tool_round"}               tools just ran; drain the record
            {"type": "error",     "message": ...}
            {"type": "meta",      "latency_ms": ..., "rounds": ...}

        The default implementation is the honest non-streaming one: run
        `generate` and emit the finished answer as a single fragment. A runtime
        that can do better overrides this. Callers must work correctly either
        way, which they do, because one fragment is a valid stream.
        """
        result = await self.generate(
            system_prompt=system_prompt,
            history=history,
            question=question,
            tools=tools,
        )
        # Tools have already run by now, so the caller's record is populated;
        # saying so keeps the event order the same on both paths.
        yield {"type": "tool_round"}
        if result.error:
            yield {"type": "error", "message": result.error}
        elif result.text:
            yield {"type": "text", "text": result.text}
        yield {"type": "meta", "latency_ms": result.latency_ms, "rounds": 1}

    @abstractmethod
    def describe_error(self, error: Exception) -> str:
        """Turn a provider exception into something worth showing a person.

        Per-provider because the useful advice is: Gemini's free-tier rate
        limit and Anthropic's billing state produce different sentences, and
        "check the server log" is useless advice to someone who cannot read it.
        """


#: One client per API key, reused across requests. The SDK holds a connection
#: pool, and building a client per question threw that pool away and paid for a
#: fresh TLS handshake to Google every time somebody asked a question.
_CLIENTS: Dict[str, Any] = {}


def _shared_client(api_key: str):
    client = _CLIENTS.get(api_key)
    if client is None:
        from google import genai

        client = _CLIENTS[api_key] = genai.Client(api_key=api_key)
    return client


def _quota_scope(error: Exception) -> Optional[str]:
    """Which quota a 429 is about: "minute", "day", or None if not a quota.

    The distinction decides what to DO, which is why it is worth teasing apart
    two errors that carry the same status code. A per-minute cap clears itself
    while the person waits, so the answer is to wait. A per-day cap does not,
    so waiting is the one thing guaranteed not to work -- that one calls for a
    different model.

    Read off the quotaId Google returns, e.g.
    GenerateRequestsPerDayPerProjectPerModel-FreeTier, with the spaces and
    underscores squeezed out so the match does not depend on formatting.
    """
    message = str(error).lower()
    if "429" not in message and "resource_exhausted" not in message:
        return None
    squashed = message.replace(" ", "").replace("_", "").replace("-", "")
    return "day" if "perday" in squashed else "minute"


def _is_retired(error: Exception) -> bool:
    """Whether the model simply is not there any more.

    Worth handling beside the quota cases because it has the same remedy and a
    different cause. Google retires models: the 2.5 Flash family already 404s
    on a key that could reach it a year ago. Without this, the day a primary
    model is withdrawn the assistant stops answering entirely, having been one
    line away from carrying on with the next model in its own chain.

    It is not hidden -- the fallback is named in the answer and logged, and if
    every model 404s the reader still gets "set ASSISTANT_MODEL to a current
    Gemini Flash model". A typo produces one loud degraded path rather than a
    dead feature.
    """
    message = str(error).lower()
    return "not_found" in message or "404" in message


#: Models currently believed to be out of daily quota, and when to re-probe.
#: Process-local by design. It is a cache of a guess, not a fact worth sharing:
#: a second replica re-learning the same thing costs one request, where a
#: shared store would need to be correct about a reset time nobody here knows.
_COOLDOWN: Dict[str, float] = {}


def _rest(model: str, reason: str = "daily_quota") -> None:
    """Put a model aside for a while. Used for both ways one becomes unusable
    without becoming unusable forever."""
    _COOLDOWN[model] = time.time() + max(0, settings.ASSISTANT_MODEL_COOLDOWN_SECONDS)
    logger.warning(
        "assistant.model_set_aside",
        extra={
            "model": model,
            "reason": reason,
            "cooldown_seconds": settings.ASSISTANT_MODEL_COOLDOWN_SECONDS,
        },
    )


def reset_cooldowns() -> None:
    """Forget which models were exhausted. For tests and for /status resets."""
    _COOLDOWN.clear()


class GeminiRuntime(LLMRuntime):
    """Google Gemini, running the tool loop by hand.

    The SDK's automatic function calling used to own this loop. It cannot any
    more, and the reason is worth writing down because it is not obvious and it
    is easy to "simplify" back into a bug:

        generate_content_stream + automatic function calling loses the answer.
        The tools run, and then a single empty chunk arrives with STOP. The
        SDK consumes the post-tool turn internally and never re-streams it.
        Measured on gemini-3.6-flash and gemini-3.1-flash-lite; without tools
        declared, the same call streams text normally.

    So the loop is ours again -- with the fix for why it was given away in the
    first place. Hand-feeding tool results back to a Gemini 3 model used to make
    it call the same tool forever instead of answering, because these models
    carry a `thought_signature` through a turn and a reconstructed turn loses
    it. The cure is to echo the model's own parts back VERBATIM rather than
    rebuilding them from the function calls we read out. That is what
    `_advance` does, and it is the single line that makes this work.

    Owning the loop also buys two things the SDK's version could not:

    *   the caller learns a tool ran WHILE it is running, rather than after the
        answer is already written, and
    *   round trips are bounded here, in the caller's units, rather than only
        inside the tools.
    """

    name = "gemini"

    def __init__(self, client=None):
        # Injectable so tests drive the whole path with a scripted fake.
        self._client = client
        #: Which model actually answered. Only differs from the configured one
        #: when the chain fell back, and the caller says so rather than letting
        #: a quieter answer look like the usual one.
        self._model: Optional[str] = None

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.GEMINI_API_KEY)

    @property
    def model(self) -> str:
        return self._model or settings.ASSISTANT_MODEL

    @staticmethod
    def chain() -> List[str]:
        """The configured model, then its fallbacks, de-duplicated."""
        raw = [settings.ASSISTANT_MODEL] + (
            settings.ASSISTANT_FALLBACK_MODELS or ""
        ).split(",")
        ordered: List[str] = []
        for name in (item.strip() for item in raw):
            if name and name not in ordered:
                ordered.append(name)
        return ordered

    def _usable(self) -> List[str]:
        """The chain minus anything cooling down.

        Falls back to the whole chain when everything is cooling down, rather
        than refusing to try. The cooldown is a guess about when a quota resets;
        a guess should never be the reason nobody gets an answer.
        """
        now = time.time()
        fresh = [name for name in self.chain() if _COOLDOWN.get(name, 0.0) <= now]
        return fresh or self.chain()

    @property
    def client(self):
        if self._client is None:
            self._client = _shared_client(settings.GEMINI_API_KEY)
        return self._client

    async def generate(self, *, system_prompt, history, question, tools) -> LLMResult:
        """The whole answer, for callers that do not want the pieces."""
        parts: List[str] = []
        error: Optional[str] = None
        latency = 0.0
        async for event in self.stream(
            system_prompt=system_prompt,
            history=history,
            question=question,
            tools=tools,
        ):
            kind = event.get("type")
            if kind == "text":
                parts.append(event["text"])
            elif kind == "error":
                error = event["message"]
            elif kind == "meta":
                latency = event.get("latency_ms", 0.0)
        return LLMResult(text="".join(parts).strip(), latency_ms=latency, error=error)

    async def stream(self, *, system_prompt, history, question, tools):
        from google.genai import types

        by_name = {fn.__name__: fn for fn in tools}
        config = self._config(types, system_prompt, tools)
        contents = self._contents(types, history, question)

        started = time.perf_counter()
        rounds = 0
        emitted_any = False

        try:
            while rounds < max(1, settings.ASSISTANT_MAX_ROUNDS):
                rounds += 1
                model_parts: List[Any] = []
                calls: List[Any] = []

                stream = await self._open(contents, config, may_switch=rounds == 1)
                async for chunk in stream:
                    for part in _parts_of(chunk):
                        model_parts.append(part)
                        if getattr(part, "function_call", None):
                            calls.append(part.function_call)
                            continue
                        text = getattr(part, "text", None)
                        # A thought part is the model's private reasoning. It
                        # is echoed back for signature continuity but never
                        # shown -- it is not the answer, and it can quote the
                        # tool results verbatim.
                        if text and not getattr(part, "thought", False):
                            emitted_any = True
                            yield {"type": "text", "text": text}

                if not calls:
                    break

                self._advance(types, contents, model_parts, calls, by_name)
                # Announced after the tools have actually run, so the caller
                # can show what was looked up while the model is still
                # deciding what to say about it.
                yield {"type": "tool_round"}
            else:
                # Loop finished on the bound rather than on an answer.
                logger.warning(
                    "assistant.rounds_exhausted",
                    extra={"rounds": rounds, "model": self.model},
                )

        except Exception as error:  # noqa: BLE001 -- reported, never raised
            logger.exception(
                "assistant.provider_failed",
                extra={"provider": self.name, "error_type": type(error).__name__},
            )
            # If the reader is already holding half an answer, a hard error
            # would replace it with an error bubble. Say the answer stopped
            # instead of pretending it never started.
            yield {
                "type": "error",
                "message": (
                    "The answer stopped part-way. " + self.describe_error(error)
                    if emitted_any
                    else self.describe_error(error)
                ),
            }

        yield {
            "type": "meta",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "rounds": rounds,
        }

    async def _open(self, contents, config, *, may_switch: bool):
        """Start one streamed turn, treating the two 429s as different problems.

        A per-minute cap clears itself while the person waits, so it is waited
        out. A per-day cap does not, so waiting is the one response guaranteed
        to fail; that model is put aside and the next one on the chain answers
        instead. On the free tier the daily cap is per model, which is what
        makes a chain worth having at all.

        Both are handled here, before anything has been shown. Once the reader
        is watching an answer arrive, starting a second one would print it
        twice.

        `may_switch` is False after the first round. Contents by then carry
        thought signatures belonging to the model that produced them, and
        handing another model somebody else's signatures is not a thing to find
        out about in production. In practice it costs nothing: a daily cap
        refuses the first request of a question, not the third.
        """
        attempts = max(1, settings.ASSISTANT_RETRY_ATTEMPTS)
        order = self._usable() if may_switch else [self.model]
        if self.model in order:
            # Carry on down the chain from wherever we already are rather than
            # starting at a model this request has already been refused by.
            order = order[order.index(self.model) :]

        last: Optional[Exception] = None
        for model in order:
            for attempt in range(1, attempts + 1):
                try:
                    stream = await self.client.aio.models.generate_content_stream(
                        model=model, contents=contents, config=config
                    )
                    # The await above sends nothing. The SDK defers the request
                    # to the first iteration, so every check below is dead code
                    # unless one chunk is actually pulled here -- which is how
                    # the retry in the previous version of this method came to
                    # be inert against the real API while passing its tests,
                    # because a fake raises from the call and the SDK does not.
                    head = await _first(stream)
                    if model != self.model:
                        logger.info(
                            "assistant.model_fallback",
                            extra={"from": self.model, "to": model},
                        )
                    self._model = model
                    return _replay(head, stream)
                except Exception as error:  # noqa: BLE001
                    scope = _quota_scope(error)
                    if scope == "day" or _is_retired(error):
                        _rest(model, "daily_quota" if scope == "day" else "retired")
                        last = error
                        break  # no amount of waiting helps; next model
                    if scope == "minute":
                        if attempt < attempts:
                            delay = 2.0 * attempt
                            logger.warning(
                                "assistant.rate_limited_retrying",
                                extra={
                                    "model": model,
                                    "attempt": attempt,
                                    "delay_seconds": delay,
                                },
                            )
                            await asyncio.sleep(delay)
                            continue
                        # Out of patience with this one, but a per-minute limit
                        # is per model too, so the next one may answer at once.
                        # Not put to rest -- it will be fine in a minute, and
                        # skipping it for an hour would waste the allowance it
                        # still has. Found by a live test: without this, a busy
                        # fallback aborted the whole chain.
                        last = error
                        break
                    raise

        # Every model on the chain is out for the day.
        raise last if last else RuntimeError("no model available")

    def _config(self, types, system_prompt, tools):
        declarations = [
            types.FunctionDeclaration.from_callable(client=self.client, callable=fn)
            for fn in tools
        ]
        return types.GenerateContentConfig(
            tools=(
                [types.Tool(function_declarations=declarations)]
                if declarations
                else None
            ),
            # We own the loop; the SDK running its own on top would double
            # every tool call and hide the round trips from the caller.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            thinking_config=self._thinking(types),
            system_instruction=system_prompt,
        )

    @staticmethod
    def _thinking(types):
        """How much silent reasoning to allow, or None to leave the default.

        Measured on this workload rather than guessed: the tools hand the model
        finished numbers, so a turn spends about 150 thinking tokens to produce
        a 45-token answer. Cutting that costs nothing the reader can see.
        """
        level = (settings.ASSISTANT_THINKING_LEVEL or "").strip().lower()
        if level in ("", "default", "auto"):
            return None
        return types.ThinkingConfig(thinking_level=level)

    @staticmethod
    def _advance(types, contents, model_parts, calls, by_name):
        """Append the model's turn and the tool results, for the next round.

        `model_parts` goes back exactly as it arrived. Rebuilding it from the
        function calls -- which reads more cleanly and is what the first
        version did -- drops `thought_signature`, and a Gemini 3 model that
        loses its signature re-issues the same tool call instead of answering.
        """
        contents.append(types.Content(role="model", parts=model_parts))

        responses = []
        for call in calls:
            fn = by_name.get(call.name)
            if fn is None:
                # The model named a tool that does not exist. Told rather than
                # raised, so it can correct itself in the next round.
                output = {
                    "error": "unknown_tool",
                    "message": f"There is no tool called {call.name}.",
                }
            else:
                output = fn(**(dict(call.args) if call.args else {}))
            responses.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=call.name, response=output
                    )
                )
            )
        contents.append(types.Content(role="user", parts=responses))

    @staticmethod
    def _contents(types, history, question):
        """Prior turns plus the new question, in the shape the SDK expects.

        History is capped by the router. Anything malformed is dropped rather
        than raised on: a bad turn in a client-supplied transcript should cost
        context, not the whole request.
        """
        contents = []
        for turn in history or []:
            role = turn.get("role")
            text = turn.get("text") or turn.get("content")
            if role in ("user", "model", "assistant") and isinstance(text, str):
                contents.append(
                    types.Content(
                        role="user" if role == "user" else "model",
                        parts=[types.Part(text=text)],
                    )
                )
        contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
        return contents

    def describe_error(self, error: Exception) -> str:
        name = type(error).__name__
        message = str(error).lower()

        if "api key" in message or "unauthenticated" in message or "401" in message:
            return "The assistant's API key was rejected. Check GEMINI_API_KEY."
        if "quota" in message or "resource_exhausted" in message or "429" in message:
            # Two different limits wear the same status code, and the advice
            # differs: a per-minute limit clears itself while the person waits,
            # a per-day one does not and no amount of patience will help.
            if "perday" in message.replace(" ", "").replace("_", ""):
                return (
                    "The assistant has used up its free quota for today. The "
                    "Gemini free tier allows only a small number of requests "
                    "per day per model. It resets tomorrow; to lift it, enable "
                    "billing on the API key or switch ASSISTANT_MODEL."
                )
            return (
                "The assistant has hit its rate limit. The Gemini free tier allows "
                "only a few requests a minute -- wait a moment and try again."
            )
        if "not_found" in message or "404" in message:
            return (
                f"The model '{self.model}' is not available to this "
                "key. Set ASSISTANT_MODEL to a current Gemini Flash model."
            )
        if "connection" in name.lower() or "timeout" in message:
            return "Couldn't reach the model. Check the connection and try again."
        # Deliberately vague as a fallback: an API error can quote request
        # content back, and that content is this tenant's data.
        return "The assistant hit an error. The details are in the server log."


_EXHAUSTED = object()


async def _first(stream):
    """Pull one chunk, which is what actually performs the request.

    Returns a sentinel for a stream that ended immediately, so that "no chunks"
    and "a falsy first chunk" stay distinguishable.
    """
    try:
        return await stream.__anext__()
    except StopAsyncIteration:
        return _EXHAUSTED


async def _replay(head, stream):
    """The stream as it would have been, with the chunk already taken put back."""
    if head is not _EXHAUSTED:
        yield head
        async for chunk in stream:
            yield chunk


def _parts_of(chunk) -> Sequence[Any]:
    """The content parts of one streamed chunk, or nothing.

    Every level of this is optional in the wire format, and a chunk carrying
    only a finish reason is normal rather than exceptional.
    """
    candidates = getattr(chunk, "candidates", None) or []
    if not candidates:
        return ()
    content = getattr(candidates[0], "content", None)
    return getattr(content, "parts", None) or () if content else ()


#: Runtimes by the value of LLM_PROVIDER.
RUNTIMES: Dict[str, type[LLMRuntime]] = {"gemini": GeminiRuntime}


def get_runtime(client=None) -> LLMRuntime:
    """The runtime this deployment is configured for.

    Falls back to Gemini rather than raising on an unknown provider: a typo in
    one environment variable should not take the whole assistant offline, and
    the /status endpoint reports which runtime is actually in use.
    """
    chosen = RUNTIMES.get(settings.LLM_PROVIDER.strip().lower())
    if chosen is None:
        logger.warning(
            "assistant.unknown_provider",
            extra={"configured": settings.LLM_PROVIDER, "using": "gemini"},
        )
        chosen = GeminiRuntime
    return chosen(client) if chosen is GeminiRuntime else chosen()
