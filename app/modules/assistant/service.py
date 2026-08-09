"""The assistant loop, on Gemini.

The model is given real Python functions rather than JSON tool declarations,
and the SDK runs the call loop itself. That is a deliberate choice made after
the manual loop failed: hand-feeding function results back to Gemini 3 produced
the same tool call again instead of an answer, because these models carry a
thought signature through a turn and reconstructing that by hand is guesswork.
The supported path works first time, so the loop is the SDK's problem.

What stays ours is everything that matters for safety and explainability:

*   Each tool below is a closure over the request's database session and the
    company_id taken from the verified JWT. Those two arguments are bound here
    and are absent from every signature the model sees, so the tenant is not
    something the model can supply, mistake, or be talked into changing.
*   Each closure records the call and the citations its result carried, so the
    answer can point at real records instead of asking to be believed.

The docstrings are not documentation. Gemini derives each tool's schema and
description from the signature and docstring, so this is the text the model
reads when deciding what to call -- written to say WHEN to use a tool, not
merely what it does.
"""

import logging
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.assistant.tools import run_tool

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the OptiStock assistant. You answer questions about \
one company's inventory using the tools provided.

Ground every factual claim in a tool result. If the tools do not cover \
something -- supplier contracts, staff, anything outside inventory -- say so \
plainly instead of guessing. Never invent a SKU, a quantity, or a figure.

Lead with the answer. A question whose answer is a number gets the number \
first, then the supporting detail. Keep responses to the length the question \
needs; a lookup deserves a sentence, not a report.

You can read but not change anything. When a user wants stock adjusted, an \
alert dismissed, or an order placed, tell them which screen does it rather \
than implying you have done it."""


def is_configured() -> bool:
    """Whether an API key is present.

    Checked before every request so a missing key produces one clear sentence
    rather than an exception trace, and so the rest of the app runs without it.
    """
    return bool(settings.GEMINI_API_KEY)


def build_client():
    """Construct the Gemini client. Imported lazily so the package is only
    required when the assistant is actually used."""
    from google import genai

    return genai.Client(api_key=settings.GEMINI_API_KEY)


def build_toolset(db: Session, company_id: UUID, record):
    """Return the tools for one request, bound to one tenant.

    `record` is called with (tool_name, arguments, citations) as each tool runs,
    which is how the transcript learns what was looked up.
    """

    def call(name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        payload, citations = run_tool(db, company_id, name, arguments)
        record(name, arguments, citations)
        return payload

    def search_products(query: str = "", abc_class: str = "") -> dict:
        """Look up products in the catalogue by name, SKU fragment, or ABC class.

        Call this when the user names a product, or asks what the company sells,
        how something is priced, or which products are A, B or C class. Returns
        cost, price and classification. Does NOT return stock levels -- use
        check_stock for those.

        Args:
            query: Text to match against product name or SKU.
            abc_class: Restrict to one revenue class: A, B or C.
        """
        return call("search_products", {"query": query, "abc_class": abc_class})

    def check_stock(sku: str = "", low_only: bool = False) -> dict:
        """Current stock on hand per product per warehouse, with reorder points.

        Call this for anything about quantities, what is running low, what is out
        of stock, or how much of something is held where. Set low_only to true
        when the user asks what needs reordering.

        Args:
            sku: Restrict to SKUs matching this text.
            low_only: Only lines at or below their reorder point.
        """
        return call("check_stock", {"sku": sku, "low_only": low_only})

    def list_alerts(severity: str = "") -> dict:
        """Open alerts raised by the background consumers, with their evidence.

        Call this when the user asks what needs attention, what is wrong, or
        about warnings and critical issues.

        Args:
            severity: Restrict to one of info, warning or critical.
        """
        return call("list_alerts", {"severity": severity})

    def trading_summary(days: int = 30) -> dict:
        """Revenue, orders, units sold and stock movements over a recent window.

        Call this for any question about sales performance, how the business is
        doing, or totals over a period.

        Args:
            days: Length of the window in days, between 7 and 90.
        """
        return call("trading_summary", {"days": days})

    def forecast_accuracy() -> dict:
        """How well the demand forecast has performed against real sales.

        Returns weighted error, average miss in units, and how many predictions
        landed within 20%. Call this whenever the user asks whether the forecast
        or the AI can be trusted, or how accurate the predictions are.
        """
        return call("forecast_accuracy", {})

    def recent_events(event_type: str = "", limit: int = 15) -> dict:
        """The most recent domain events: stock movements, sales, scans, alerts.

        Call this when the user asks what has been happening, what changed
        recently, or about activity.

        Args:
            event_type: Exact type, e.g. stock.moved, sale.completed,
                stock.depleted, scan.recorded.
            limit: How many events to return, between 1 and 25.
        """
        return call("recent_events", {"event_type": event_type, "limit": limit})

    def warehouse_overview() -> dict:
        """Every warehouse with how many stock lines and units it holds.

        Call this when the user asks about locations, sites, or where stock sits.
        """
        return call("warehouse_overview", {})

    return [
        search_products,
        check_stock,
        list_alerts,
        trading_summary,
        forecast_accuracy,
        recent_events,
        warehouse_overview,
    ]


async def converse(
    client,
    db: Session,
    company_id: UUID,
    question: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Answer one question, yielding progress the router forwards to the browser.

    {"type": "tool",     "name": ..., "input": ...}  -- a tool that ran
    {"type": "text",     "text": ...}                -- the answer
    {"type": "citation", "citation": {...}}          -- a record it used
    {"type": "done"}
    {"type": "error",    "message": ...}
    """
    from google.genai import types

    used: List[Dict[str, Any]] = []
    citations: List[Dict[str, str]] = []
    seen: set = set()

    def record(name, arguments, tool_citations):
        used.append({"name": name, "input": arguments})
        for citation in tool_citations:
            key = (citation["type"], citation["ref"])
            if key not in seen:
                seen.add(key)
                citations.append(citation)

    config = types.GenerateContentConfig(
        tools=build_toolset(db, company_id, record),
        system_instruction=SYSTEM_PROMPT,
    )

    try:
        # The async client, so the tool loop does not block the event loop for
        # every other request the process is serving. The tools themselves are
        # synchronous database calls and the SDK runs them off-thread.
        response = await client.aio.models.generate_content(
            model=settings.ASSISTANT_MODEL,
            contents=_as_contents(types, history, question),
            config=config,
        )
    except Exception as e:
        logger.exception("Assistant request failed")
        yield {"type": "error", "message": _describe(e)}
        return

    for call in used:
        yield {"type": "tool", **call}
    for citation in citations:
        # Nested rather than spread: a citation carries its own `type`
        # ("product", "alert"), which would otherwise overwrite the envelope's
        # and leave the client with an event kind it cannot handle.
        yield {"type": "citation", "citation": citation}

    text = (response.text or "").strip()
    if not text:
        # An empty answer with tools run is a real outcome worth naming rather
        # than rendering as a blank bubble.
        yield {
            "type": "error",
            "message": "The model returned no answer. Try rephrasing the question.",
        }
        return

    yield {"type": "text", "text": text}
    yield {"type": "done", "rounds": len(used)}


def _as_contents(types, history, question):
    """Prior turns plus the new question, in the shape the SDK expects.

    History is capped by the router. Anything malformed is dropped rather than
    raised on: a bad turn in a client-supplied transcript should cost context,
    not the whole request.
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


def _describe(error: Exception) -> str:
    """Turn an SDK exception into something worth showing a person.

    Deliberately vague as a fallback -- an API error can quote request content
    back, and that content is this tenant's data. Conditions the reader can act
    on are named, because "check the server log" is useless advice to someone
    who cannot read it.
    """
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
            f"The model '{settings.ASSISTANT_MODEL}' is not available to this "
            "key. Set ASSISTANT_MODEL to a current Gemini Flash model."
        )
    if "connection" in name.lower() or "timeout" in message:
        return "Couldn't reach the model. Check the connection and try again."
    return "The assistant hit an error. The details are in the server log."
