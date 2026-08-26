"""A short-lived cache for tool results.

A single question routinely asks the same thing twice. "What's low, and how bad
is the worst one?" makes the model call check_stock, read the answer, and call
check_stock again to compare -- and each of those is a real query against a
table that has not changed in the intervening two hundred milliseconds.

So the results are cached for a few tens of seconds. The TTL is the whole
design, and it is short on purpose: this is inventory data, and an answer built
on stock levels from five minutes ago is worse than a slow one. Long enough to
cover a single conversation's repeated lookups, short enough that a scan or a
sale shows up while the person is still looking at the screen.

Three properties matter more than the speed:

*   **The tenant is part of the key.** This is a process-wide dictionary in a
    multi-tenant application, which is exactly the shape of an accidental
    cross-tenant read. company_id is the first element of every key, so two
    companies asking the same question cannot collide. There is a test for it,
    and it is the test to read first.
*   **Only reads are cached.** A tool that proposes or changes anything is
    never served from here, no matter how identical the arguments look.
*   **It is bounded.** maxsize evicts least-recently-used, so a long-running
    process cannot grow this without limit.

Deliberately in-memory rather than in Redis. Redis is already a dependency, but
a cache with a 45-second TTL saves a query that takes a millisecond -- crossing
a network to avoid that trade is a worse deal, and a per-process cache cannot
develop a coherence bug across replicas because nothing depends on it agreeing.
"""

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from cachetools import TTLCache

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Tools safe to serve from cache. An allow-list rather than a deny-list: a
#: tool added later is uncached until someone decides otherwise, which is the
#: direction that fails safely.
CACHEABLE = frozenset(
    {
        "search_products",
        "check_stock",
        "list_alerts",
        "trading_summary",
        "forecast_accuracy",
        "recent_events",
        "warehouse_overview",
        "stockout_risk",
    }
)

# Guarded by a lock because FastAPI runs these synchronous tools in a thread
# pool, so two requests genuinely do touch this at the same time. TTLCache is
# not thread-safe, and its own docs say so.
_LOCK = threading.Lock()
_CACHE: TTLCache = TTLCache(maxsize=512, ttl=max(1, settings.TOOL_CACHE_TTL_SECONDS))

#: Counters for the benchmark utility and for /status. Not metrics-grade;
#: enough to answer "is the cache doing anything".
_STATS = {"hits": 0, "misses": 0, "skipped": 0}


def _key(company_id: UUID, name: str, arguments: Dict[str, Any]) -> Tuple:
    """company_id first, always.

    Arguments are sorted so that {"sku": "X", "low_only": True} and
    {"low_only": True, "sku": "X"} are one entry rather than two, and stringified
    so an unhashable value cannot raise from inside a cache lookup.
    """
    return (
        str(company_id),
        name,
        tuple(sorted((k, repr(v)) for k, v in (arguments or {}).items())),
    )


def get(company_id: UUID, name: str, arguments: Dict[str, Any]) -> Optional[Any]:
    """A cached result, or None. None is also a legitimate absence -- tools
    never return None, so there is no ambiguity to resolve."""
    if name not in CACHEABLE:
        _STATS["skipped"] += 1
        return None

    with _LOCK:
        hit = _CACHE.get(_key(company_id, name, arguments))

    if hit is None:
        _STATS["misses"] += 1
        return None

    _STATS["hits"] += 1
    logger.debug("assistant.cache_hit", extra={"tool": name})
    return hit


def put(company_id: UUID, name: str, arguments: Dict[str, Any], value: Any) -> None:
    if name not in CACHEABLE:
        return
    with _LOCK:
        _CACHE[_key(company_id, name, arguments)] = value


def clear() -> None:
    """Empty the cache. Used by tests, and by anything that needs a hard reset."""
    with _LOCK:
        _CACHE.clear()
    for key in _STATS:
        _STATS[key] = 0


def stats() -> Dict[str, Any]:
    with _LOCK:
        size = len(_CACHE)
    total = _STATS["hits"] + _STATS["misses"]
    return {
        **_STATS,
        "entries": size,
        "ttl_seconds": _CACHE.ttl,
        "hit_rate": round(_STATS["hits"] / total, 3) if total else None,
    }


# ---------------------------------------------------------------------------
# Whole answers
#
# The tool cache above saves a database query, which is worth a millisecond.
# This one saves a REQUEST, which on a free-tier key is worth considerably
# more: the Gemini free tier allows a fixed number of requests per model per
# day, and a question answered from here spends none of them.
#
# It is a stricter cache than the one above, and every restriction is there
# because replaying an answer is a stronger claim than replaying a row:
#
# *   **Only first turns.** A follow-up means whatever the previous turn said.
#     "And the other warehouse?" has no answer on its own, so anything with
#     history behind it is never stored and never served.
# *   **Only if every tool it used was a read.** The allow-list is the same one
#     the tool cache uses, so a tool added later is excluded until somebody
#     decides otherwise. This is what keeps create_purchase_order out: an
#     answer that says "it is waiting for your approval" is TRUE the first time
#     and a lie every time after, because replaying it proposes nothing.
# *   **Only clean answers.** Anything the output filter flagged, anything that
#     errored, and anything empty is not worth keeping and not safe to repeat.
#
# The TTL is short for the reason the one above is short, and then shorter
# again for one that does not apply to tools: someone who asks the same
# question twice is often asking BECAUSE they expect the answer to have
# changed. "Is it still low?" deserves a fresh look, so this window is sized
# for a refresh or a double-tap rather than for a conversation.
# ---------------------------------------------------------------------------

_ANSWER_LOCK = threading.Lock()
_ANSWERS: TTLCache = TTLCache(
    maxsize=256, ttl=max(1, settings.ANSWER_CACHE_TTL_SECONDS)
)
_ANSWER_STATS = {"hits": 0, "misses": 0, "skipped": 0}


def _answer_key(company_id: UUID, question: str) -> Tuple:
    """company_id first, always -- same rule, same reason, same test.

    Whitespace and case are normalised so "What is low?" and "what is low?"
    are one entry. Nothing cleverer: two questions that differ by a word are
    two questions, and a fuzzy match here would answer one of them with the
    other one's answer.
    """
    return (str(company_id), " ".join((question or "").lower().split()))


def answer_for(
    company_id: UUID, question: str, has_history: bool
) -> Optional[Dict[str, Any]]:
    """A stored answer for this exact question, or None."""
    if has_history or settings.ANSWER_CACHE_TTL_SECONDS <= 0:
        _ANSWER_STATS["skipped"] += 1
        return None

    with _ANSWER_LOCK:
        hit = _ANSWERS.get(_answer_key(company_id, question))

    if hit is None:
        _ANSWER_STATS["misses"] += 1
        return None

    _ANSWER_STATS["hits"] += 1
    logger.info("assistant.answer_cache_hit", extra={"saved_request": True})
    return hit


def remember_answer(
    company_id: UUID,
    question: str,
    *,
    has_history: bool,
    text: str,
    tools_used: List[str],
    citations: List[Dict[str, str]],
    flags: List[str],
) -> None:
    """Store an answer, if it is one of the kinds that may be repeated."""
    if (
        has_history
        or settings.ANSWER_CACHE_TTL_SECONDS <= 0
        or not text
        or flags
        or any(name not in CACHEABLE for name in tools_used)
    ):
        return

    with _ANSWER_LOCK:
        _ANSWERS[_answer_key(company_id, question)] = {
            "text": text,
            "tools": list(tools_used),
            "citations": list(citations),
        }


def clear_answers() -> None:
    with _ANSWER_LOCK:
        _ANSWERS.clear()
    for key in _ANSWER_STATS:
        _ANSWER_STATS[key] = 0


def answer_stats() -> Dict[str, Any]:
    with _ANSWER_LOCK:
        size = len(_ANSWERS)
    total = _ANSWER_STATS["hits"] + _ANSWER_STATS["misses"]
    return {
        **_ANSWER_STATS,
        "entries": size,
        "ttl_seconds": _ANSWERS.ttl,
        "hit_rate": round(_ANSWER_STATS["hits"] / total, 3) if total else None,
    }
