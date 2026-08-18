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
from typing import Any, Dict, Optional, Tuple
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
