"""The agentic loop: ask Claude, run the tools it asks for, ask again.

A hand-written loop rather than the SDK's tool runner, for one reason the runner
does not accommodate cleanly: every tool here needs `company_id` bound from the
verified JWT and hidden from the model, and every tool result has to be
intercepted on the way past so its citations can be collected. Owning the loop
makes both explicit rather than smuggling request state through closures.

The loop is also the part worth testing, and it is testable without a network:
`converse` takes its Anthropic client as an argument, so a fake that returns
scripted responses exercises the whole thing -- tool dispatch, tenant binding,
citation collection, the iteration cap -- with no API key and no cost.
"""

import json
import logging
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.modules.assistant.tools import TOOLS, run_tool

logger = logging.getLogger(__name__)

# Every tool is read-only and the catalogue is small, so a runaway loop costs
# tokens rather than damage -- but it still costs tokens. Six rounds is enough
# for "find the product, check its stock, check its alerts" and well short of
# anything pathological.
MAX_ROUNDS = 6

SYSTEM_PROMPT = """You are the OptiStock assistant. You answer questions about \
one company's inventory using the tools provided.

Ground every factual claim in a tool result. If the tools do not cover \
something -- supplier contracts, staff, anything outside inventory -- say so \
plainly instead of guessing. Never invent a SKU, a quantity, or a figure.

Lead with the answer. A question with a number as its answer gets the number \
first, then the supporting detail. Keep responses to the length the question \
needs; a lookup deserves a sentence, not a report.

You can read but not change anything. When a user wants stock adjusted, an \
alert dismissed, or an order placed, tell them which screen does it rather \
than implying you have done it.

Figures from trading_summary come from a projection updated by background \
workers, so they are current to within about a second. Say so only if asked."""


def is_configured() -> bool:
    """Whether an API key is present.

    Checked before every request so a missing key produces one clear sentence
    rather than an exception trace, and so the rest of the app runs normally
    without one.
    """
    return bool(settings.ANTHROPIC_API_KEY)


def build_client():
    """Construct the async Anthropic client. Imported lazily so the package is
    only required when the assistant is actually used."""
    from anthropic import AsyncAnthropic

    return AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)


def _text_of(content) -> str:
    return "".join(block.text for block in content if block.type == "text")


async def converse(
    client,
    db: Session,
    company_id: UUID,
    question: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Run the loop, yielding progress as it goes.

    Yields dicts the router forwards to the browser:
      {"type": "tool",     "name": ..., "input": ...}  -- about to run a tool
      {"type": "text",     "text": ...}                -- a chunk of the answer
      {"type": "citation", ...}                        -- a record the answer used
      {"type": "done",     "rounds": n}
      {"type": "error",    "message": ...}
    """
    messages: List[Dict[str, Any]] = list(history or [])
    messages.append({"role": "user", "content": question})

    seen_citations: set = set()

    for round_number in range(1, MAX_ROUNDS + 1):
        try:
            # Streamed rather than awaited whole: a tool-using turn can take
            # several seconds, and a page that shows nothing until the end
            # looks broken even when it is working.
            async with client.messages.stream(
                model=settings.ASSISTANT_MODEL,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            ) as stream:
                async for text in stream.text_stream:
                    yield {"type": "text", "text": text}
                response = await stream.get_final_message()
        except Exception as e:
            logger.exception("Assistant request failed")
            yield {"type": "error", "message": _describe(e)}
            return

        # Checked before reading content: a refused response can carry no text
        # at all, and indexing into it would raise instead of explaining.
        if response.stop_reason == "refusal":
            yield {
                "type": "error",
                "message": "That request was declined. Try rephrasing the question.",
            }
            return

        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            yield {"type": "done", "rounds": round_number}
            return

        results = []
        for call in tool_uses:
            yield {"type": "tool", "name": call.name, "input": call.input}

            # The DB driver is synchronous. Calling it directly here would block
            # the event loop for the length of the query and stall every other
            # request the process is serving, streaming ones included.
            payload, citations = await run_in_threadpool(
                run_tool, db, company_id, call.name, call.input
            )

            for citation in citations:
                key = (citation["type"], citation["ref"])
                if key not in seen_citations:
                    seen_citations.add(key)
                    # Nested, not spread. A citation carries its own `type`
                    # ("product", "alert", ...), which spreading would use to
                    # overwrite the envelope's `type` -- the client would then
                    # see an event kind it has no handler for and drop every
                    # citation on the floor.
                    yield {"type": "citation", "citation": citation}

            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(payload, default=str),
                }
            )

        # All results in ONE user message. Splitting them across several
        # messages teaches the model to stop making parallel calls.
        messages.append({"role": "user", "content": results})

    # Fell out of the loop still calling tools.
    yield {
        "type": "error",
        "message": (
            f"Stopped after {MAX_ROUNDS} rounds of tool calls without reaching an "
            "answer. Try asking something narrower."
        ),
    }


def _describe(error: Exception) -> str:
    """Turn an SDK exception into something worth showing a person.

    Deliberately vague as a fallback -- an API error can quote request content
    back, and that content is this tenant's data. But conditions the reader can
    actually fix are named, because "check the server log" is useless advice to
    someone who cannot read it.
    """
    name = type(error).__name__
    message = str(error).lower()

    if "Authentication" in name:
        return "The assistant's API key was rejected. Check ANTHROPIC_API_KEY."
    # Valid key, unpaid account. Worth its own message: it arrives as a generic
    # 400 and is otherwise indistinguishable from a malformed request, which
    # sends whoever is debugging it looking in entirely the wrong place.
    if "credit balance" in message or "billing" in message:
        return (
            "The Anthropic account has no credits. Add them under Plans & "
            "Billing at console.anthropic.com; the key itself is fine."
        )
    if "RateLimit" in name:
        return "The assistant is rate limited right now. Try again shortly."
    if "Connection" in name or "Timeout" in name:
        return "Couldn't reach the model. Check the connection and try again."
    return "The assistant hit an error. The details are in the server log."
