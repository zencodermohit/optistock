"""The provider boundary.

Everything that knows a particular vendor's SDK exists below this line;
everything above it -- tenant binding, the tool budget, redaction, validation,
citations -- is ours and stays put when the vendor changes.

That is not a hypothetical. This project has already moved once, from Anthropic
to Gemini, and the move touched the loop, the error strings, the tests and the
tool declarations because none of it was separated. This module is the lesson
from that migration written down: a second move should be one new subclass.

The interface is deliberately narrow. A runtime is handed a system prompt, a
conversation, and a list of plain Python functions, and returns text. How it
gets there -- whether the SDK runs the tool loop or the runtime runs it by hand
-- is the runtime's business.

    tools as Python callables      Gemini derives its schemas by introspection.
                                   A provider needing JSON declarations can
                                   read app.modules.assistant.tools.TOOLS and
                                   dispatch by __name__; the callables carry
                                   the tenant binding either way, which is the
                                   property that must not vary by provider.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

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
    """One model provider, reduced to the two things the app needs from it."""

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

    @abstractmethod
    def describe_error(self, error: Exception) -> str:
        """Turn a provider exception into something worth showing a person.

        Per-provider because the useful advice is: Gemini's free-tier rate
        limit and Anthropic's billing state produce different sentences, and
        "check the server log" is useless advice to someone who cannot read it.
        """


class GeminiRuntime(LLMRuntime):
    """Google Gemini, using the SDK's automatic function calling.

    The SDK owns the tool loop. That is a deliberate choice made after the
    manual loop failed: hand-feeding function results back to Gemini 3 produced
    the same tool call again instead of an answer, because these models carry a
    thought signature through a turn and reconstructing it by hand is guesswork.

    The cost of giving up the loop is that iteration count is no longer
    something the caller can bound, which is why the tool budget is enforced
    inside the tools themselves. See build_toolset in service.py.
    """

    name = "gemini"

    def __init__(self, client=None):
        # Injectable so tests drive the whole path with a scripted fake, and so
        # the caller can reuse one client across a request.
        self._client = client

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.GEMINI_API_KEY)

    @property
    def client(self):
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return self._client

    async def generate(self, *, system_prompt, history, question, tools) -> LLMResult:
        from google.genai import types

        config = types.GenerateContentConfig(
            tools=list(tools),
            system_instruction=system_prompt,
        )

        started = time.perf_counter()
        try:
            # The async client, so the tool loop does not block the event loop
            # for every other request the process is serving. The tools are
            # synchronous database calls and the SDK runs them off-thread.
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=self._contents(types, history, question),
                config=config,
            )
        except Exception as error:
            logger.exception(
                "assistant.provider_failed",
                extra={"provider": self.name, "error_type": type(error).__name__},
            )
            return LLMResult(
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                error=self.describe_error(error),
            )

        return LLMResult(
            text=(response.text or "").strip(),
            latency_ms=round((time.perf_counter() - started) * 1000, 1),
        )

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
