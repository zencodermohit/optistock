"""The tool cache: does it help, and can it leak.

The second question is the one that matters. A process-wide dictionary in a
multi-tenant application is the classic shape of an accidental cross-tenant
read -- get the key wrong and company A is served company B's stock levels,
silently, with no error anywhere. That test is first for a reason.
"""

import time

from cachetools import TTLCache

from app.modules.assistant import cache
from app.modules.assistant.tools import run_tool


def test_two_companies_asking_the_same_question_do_not_share_an_answer(
    db_session, company, other_company, make_product
):
    """The cache key starts with company_id. This is the test to read first.

    Both companies run the identical call with identical arguments. If
    company_id were missing from the key, the second caller would be served the
    first one's rows -- a total tenancy failure, with nothing logged and nothing
    raised.
    """
    make_product(company, sku="A-ONLY", name="Widget")
    make_product(other_company, sku="B-ONLY", name="Widget")
    db_session.commit()

    mine, _ = run_tool(db_session, company.id, "search_products", {"query": "Widget"})
    theirs, _ = run_tool(
        db_session, other_company.id, "search_products", {"query": "Widget"}
    )

    assert [p["sku"] for p in mine["products"]] == ["A-ONLY"]
    assert [p["sku"] for p in theirs["products"]] == ["B-ONLY"]


def test_a_repeated_call_is_served_from_cache(db_session, company, make_product):
    make_product(company, sku="CACHE-1")
    db_session.commit()

    run_tool(db_session, company.id, "search_products", {"query": "CACHE"})
    before = cache.stats()["hits"]
    run_tool(db_session, company.id, "search_products", {"query": "CACHE"})

    assert cache.stats()["hits"] == before + 1


def test_argument_order_does_not_create_a_second_entry(db_session, company):
    run_tool(db_session, company.id, "check_stock", {"sku": "X", "low_only": True})
    run_tool(db_session, company.id, "check_stock", {"low_only": True, "sku": "X"})

    assert cache.stats()["entries"] == 1
    assert cache.stats()["hits"] == 1


def test_different_arguments_are_different_entries(db_session, company):
    run_tool(db_session, company.id, "check_stock", {"low_only": True})
    run_tool(db_session, company.id, "check_stock", {"low_only": False})

    assert cache.stats()["entries"] == 2
    assert cache.stats()["hits"] == 0


def test_a_company_id_in_the_arguments_cannot_vary_the_key(
    db_session, company, other_company, make_product
):
    """Stripped before the key is built, so an injected company_id can neither
    reach another tenant nor fragment this one's cache."""
    make_product(company, sku="KEY-1")
    db_session.commit()

    run_tool(db_session, company.id, "search_products", {})
    run_tool(
        db_session, company.id, "search_products", {"company_id": str(other_company.id)}
    )

    assert cache.stats()["hits"] == 1
    assert cache.stats()["entries"] == 1


def test_a_mutated_result_does_not_corrupt_the_cache(db_session, company, make_product):
    """Callers get a copy.

    The redactor rewrites SKUs in place on the way to the model. If it were
    editing the cached object, the next reader -- possibly a different request
    -- would be handed pseudonyms instead of data.
    """
    make_product(company, sku="MUTATE-1")
    db_session.commit()

    first, _ = run_tool(db_session, company.id, "search_products", {})
    first["products"][0]["sku"] = "TAMPERED"

    second, _ = run_tool(db_session, company.id, "search_products", {})
    assert second["products"][0]["sku"] == "MUTATE-1"


def test_entries_expire(db_session, company, monkeypatch):
    """A short TTL is the entire safety argument for caching stock data."""
    # The whole cache is swapped rather than its ttl patched: TTLCache.ttl is a
    # read-only property, and an entry's expiry is fixed when it is written.
    monkeypatch.setattr(cache, "_CACHE", TTLCache(maxsize=16, ttl=0.05))
    cache.clear()

    run_tool(db_session, company.id, "warehouse_overview", {})
    time.sleep(0.1)
    run_tool(db_session, company.id, "warehouse_overview", {})

    assert cache.stats()["hits"] == 0
    assert cache.stats()["misses"] == 2


def test_only_allow_listed_tools_are_cached(db_session, company):
    """An allow-list, so a tool added later is uncached until someone decides
    otherwise. That is the direction that fails safely -- particularly for the
    write-proposal tools, which must never be replayed from memory."""
    assert "create_purchase_order" not in cache.CACHEABLE
    assert "approve_purchase_order" not in cache.CACHEABLE

    run_tool(db_session, company.id, "no_such_tool", {})
    assert cache.stats()["entries"] == 0
