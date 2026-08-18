"""Predicting when stock runs out.

The arithmetic is simple enough that the interesting tests are about the cases
where simple arithmetic gives a wrong-looking answer: nothing sold, nothing
left, a sale in one warehouse and not another, and a velocity computed over the
wrong denominator.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.stockout import (
    CRITICAL_DAYS,
    HORIZON_CAP_DAYS,
    stockout_risks,
    summarise,
)
from app.modules.assistant.tools import run_tool
from app.modules.sales.models import Sale, SaleItem


@pytest.fixture
def sell(db_session, company, make_customer):
    """Record a sale of `quantity` units, `days_ago` days back."""
    customer = make_customer(company)

    def _sell(product, warehouse, quantity, days_ago=1):
        sale = Sale(
            company_id=company.id,
            customer_id=customer.id,
            source_warehouse_id=warehouse.id,
            status="completed",
            total_amount=quantity * 10,
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        db_session.add(sale)
        db_session.flush()
        db_session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=10,
            )
        )
        db_session.flush()
        return sale

    return _sell


def test_days_remaining_is_stock_over_velocity(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    product = make_product(company, sku="VELO-1")
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=300)
    # 300 units sold across the window -> 10/day -> 30 days of cover.
    for day in range(1, 11):
        sell(product, warehouse, 30, days_ago=day)
    db_session.commit()

    risk = next(r for r in stockout_risks(db_session, company.id) if r.sku == "VELO-1")

    assert risk.daily_usage == pytest.approx(10.0, abs=0.01)
    assert risk.days_remaining == pytest.approx(30.0, abs=0.5)


def test_velocity_divides_by_the_window_not_by_the_days_that_had_sales(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """The trap the demand forecast fell into and had to be corrected for.

    Ten units on one day of thirty is 0.33/day, not 10/day. The difference
    between those is the difference between a calm week and a panic.
    """
    product = make_product(company, sku="SPIKE-1")
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=100)
    sell(product, warehouse, 10, days_ago=3)
    db_session.commit()

    risk = next(r for r in stockout_risks(db_session, company.id) if r.sku == "SPIKE-1")

    assert risk.daily_usage == pytest.approx(10 / 30, abs=0.01)
    assert risk.active_days == 1
    # And it says so: one day of data is not evidence of a rate.
    assert risk.confidence == "low"


def test_a_line_with_no_sales_is_idle_rather_than_healthy(
    db_session, company, make_product, make_warehouse, make_stock
):
    """ "Unmeasured" and "fine" are different claims.

    Calling a product with no sales history "ok" quietly promotes an unknown
    into a reassurance, which is the failure mode that gets a dead SKU ignored
    for a year.
    """
    product = make_product(company, sku="IDLE-1")
    make_stock(product, make_warehouse(company), quantity=50)
    db_session.commit()

    risk = next(r for r in stockout_risks(db_session, company.id) if r.sku == "IDLE-1")

    assert risk.severity == "idle"
    assert risk.days_remaining is None
    assert "no usage to project from" in risk.explanation


def test_something_already_out_of_stock_is_critical(
    db_session, company, make_product, make_warehouse, make_stock
):
    product = make_product(company, sku="EMPTY-1")
    make_stock(product, make_warehouse(company), quantity=0)
    db_session.commit()

    risk = next(r for r in stockout_risks(db_session, company.id) if r.sku == "EMPTY-1")

    assert risk.severity == "critical"
    assert risk.days_remaining == 0
    assert "Out of stock" in risk.explanation


def test_a_fast_seller_outranks_a_bigger_pile_that_moves_slowly(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """The reason this screen exists.

    A reorder point compares units against a static threshold and would rank
    these the other way round -- the bigger pile looks safer. Days remaining
    puts them in the order somebody would actually work them.
    """
    warehouse = make_warehouse(company)

    fast = make_product(company, sku="FAST-1")
    make_stock(fast, warehouse, quantity=200)
    for day in range(1, 21):
        sell(fast, warehouse, 60, days_ago=day)  # 40/day -> 5 days left

    slow = make_product(company, sku="SLOW-1")
    make_stock(slow, warehouse, quantity=2000)
    for day in range(1, 21):
        sell(slow, warehouse, 1, days_ago=day)  # ~0.7/day -> years
    db_session.commit()

    ranked = [r.sku for r in stockout_risks(db_session, company.id)]

    assert ranked.index("FAST-1") < ranked.index("SLOW-1")
    fast_risk = next(
        r for r in stockout_risks(db_session, company.id) if r.sku == "FAST-1"
    )
    assert fast_risk.days_remaining <= CRITICAL_DAYS
    assert fast_risk.severity == "critical"


def test_velocity_is_measured_per_warehouse(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """A product selling fast in one site and sitting still in another has two
    answers, and averaging them describes neither."""
    product = make_product(company, sku="SPLIT-1")
    busy = make_warehouse(company, name="Busy")
    quiet = make_warehouse(company, name="Quiet")
    make_stock(product, busy, quantity=100)
    make_stock(product, quiet, quantity=100)
    for day in range(1, 16):
        sell(product, busy, 20, days_ago=day)
    db_session.commit()

    rows = {
        r.warehouse_name: r
        for r in stockout_risks(db_session, company.id)
        if r.sku == "SPLIT-1"
    }

    assert rows["Busy"].daily_usage > 0
    assert rows["Quiet"].daily_usage == 0
    assert rows["Quiet"].severity == "idle"


def test_an_enormous_cover_is_capped_rather_than_reported(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """4,000 days of cover is not a risk, it is an overstock -- a different
    report. Capping keeps the number from reading as a prediction."""
    product = make_product(company, sku="HOARD-1")
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=1_000_000)
    sell(product, warehouse, 1, days_ago=2)
    db_session.commit()

    risk = next(r for r in stockout_risks(db_session, company.id) if r.sku == "HOARD-1")

    assert risk.days_remaining == HORIZON_CAP_DAYS
    assert risk.severity == "ok"


def test_another_tenants_stock_never_appears(
    db_session, company, other_company, make_product, make_warehouse, make_stock
):
    """An inventory row has no company_id of its own -- it is tenanted by the
    warehouse it points at, so the join IS the check."""
    mine = make_product(company, sku="MINE-SO")
    theirs = make_product(other_company, sku="THEIRS-SO")
    make_stock(mine, make_warehouse(company), quantity=10)
    make_stock(theirs, make_warehouse(other_company), quantity=10)
    db_session.commit()

    skus = [r.sku for r in stockout_risks(db_session, company.id)]

    assert "MINE-SO" in skus
    assert "THEIRS-SO" not in skus


def test_every_row_carries_the_numbers_behind_its_prediction(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """Item 14 of the spec: a forecast a person cannot check is one they will
    either over-trust or ignore."""
    product = make_product(company, sku="SHOWWORK-1", name="Show widget")
    warehouse = make_warehouse(company)
    stock = make_stock(product, warehouse, quantity=100)
    stock.reorder_point = 40
    for day in range(1, 11):
        sell(product, warehouse, 15, days_ago=day)
    db_session.commit()

    risk = next(
        r for r in stockout_risks(db_session, company.id) if r.sku == "SHOWWORK-1"
    )

    assert risk.on_hand == 100
    assert risk.reorder_point == 40
    assert risk.daily_usage > 0
    assert risk.days_remaining is not None
    assert risk.stockout_date is not None
    assert risk.days_to_reorder_point is not None
    # And the sentence names all four, so the assistant does not have to
    # reassemble them and get one wrong.
    for fragment in ("100", "5.0/day", "reorder point of 40"):
        assert fragment in risk.explanation


def test_the_summary_names_the_soonest(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    warehouse = make_warehouse(company)
    urgent = make_product(company, sku="SOONEST-1")
    make_stock(urgent, warehouse, quantity=10)
    for day in range(1, 11):
        sell(urgent, warehouse, 30, days_ago=day)
    db_session.commit()

    summary = summarise(stockout_risks(db_session, company.id))

    assert summary["soonest"]["sku"] == "SOONEST-1"
    assert summary["counts"]["critical"] >= 1
    assert summary["at_risk"] >= 1


# ---------------------------------------------------------------------------
# Through the assistant
# ---------------------------------------------------------------------------
def test_the_tool_hands_the_model_a_ready_made_explanation(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """Computed server-side deliberately. A model given four numbers will write
    a fifth, and a stockout date it derived itself is one nobody can check."""
    product = make_product(company, sku="TOOL-SO")
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=60)
    for day in range(1, 11):
        sell(product, warehouse, 30, days_ago=day)
    db_session.commit()

    result, citations = run_tool(db_session, company.id, "stockout_risk", {})

    row = next(r for r in result["at_risk"] if r["sku"] == "TOOL-SO")
    assert row["why"]
    assert row["on_hand"] == 60
    assert row["days_remaining"] is not None
    assert row["severity"] == "critical"
    assert citations


def test_the_tool_can_be_narrowed_to_a_horizon(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    warehouse = make_warehouse(company)
    soon = make_product(company, sku="SOON-SO")
    make_stock(soon, warehouse, quantity=20)
    for day in range(1, 11):
        sell(soon, warehouse, 30, days_ago=day)

    later = make_product(company, sku="LATER-SO")
    make_stock(later, warehouse, quantity=5000)
    for day in range(1, 11):
        sell(later, warehouse, 3, days_ago=day)
    db_session.commit()

    result, _ = run_tool(db_session, company.id, "stockout_risk", {"days": 14})

    skus = [r["sku"] for r in result["at_risk"]]
    assert "SOON-SO" in skus
    assert "LATER-SO" not in skus
