"""The Products read models.

Two things here are worth pinning down.

The first is the classification. Every product lands in exactly one bucket, and
which one depends on a priority order that is a judgement rather than a fact --
a product that is both out of stock and growing is reported as critical. That
kind of rule is invisible once written and silently changes meaning when
somebody reorders the branches, so each branch gets a test.

The second is a regression. The unfiltered payload caps `products` at the top
200 by revenue. Filtering that list in the browser would have dropped every dead
product, because a dead product's defining feature is that it earned nothing --
it sorts last and falls off the end. The workspace built to find dead stock
would have found none, convincingly. The filter runs on the server, before the
cap, and this file makes sure it stays there.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.products.command_center import (
    HOLDING_COST_RATE,
    SEASONALITY_MONTHS,
    _health,
    product_command_center,
)
from app.modules.products.intelligence import (
    AT_RISK_COVER_DAYS,
    DEAD_DAYS,
    GROWTH_THRESHOLD,
    OVERSTOCK_COVER_DAYS,
    _classify,
    product_intelligence,
)
from app.modules.sales.models import Sale, SaleItem


@pytest.fixture
def sell(db_session, company, make_customer):
    customer = make_customer(company)

    def _sell(product, warehouse, quantity, days_ago=1, unit_price=100):
        sale = Sale(
            company_id=company.id,
            customer_id=customer.id,
            source_warehouse_id=warehouse.id,
            status="completed",
            total_amount=quantity * unit_price,
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        db_session.add(sale)
        db_session.flush()
        db_session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=unit_price,
            )
        )
        db_session.flush()

    return _sell


# ---------------------------------------------------------------------------
# The classification, branch by branch
# ---------------------------------------------------------------------------


def test_selling_with_nothing_on_the_shelf_is_critical():
    assert (
        _classify(on_hand=0, daily_rate=2.0, days_since_sale=1, growth=None)
        == "critical"
    )


def test_critical_beats_growing():
    """Priority, not a coincidence.

    A product that is out of stock AND growing is reported as critical, because
    the growth is the reason the stockout matters rather than a separate finding
    to be shown alongside it. Reordering the branches would break this and
    nothing else would notice.
    """
    assert (
        _classify(on_hand=0, daily_rate=2.0, days_since_sale=1, growth=5.0)
        == "critical"
    )


def test_nothing_selling_and_nothing_in_stock_is_not_critical():
    """No demand means no lost sales, whatever the shelf says."""
    assert (
        _classify(on_hand=0, daily_rate=0.0, days_since_sale=1, growth=None)
        != "critical"
    )


def test_thin_cover_is_at_risk():
    # Exactly at the threshold counts. A boundary that only fires below the
    # limit is the same off-by-one that once emptied the Analytics risk bands.
    on_hand = int(AT_RISK_COVER_DAYS * 2)
    assert (
        _classify(on_hand, daily_rate=2.0, days_since_sale=1, growth=None) == "at_risk"
    )


def test_silent_with_stock_is_dead():
    assert (
        _classify(on_hand=50, daily_rate=0.0, days_since_sale=DEAD_DAYS, growth=None)
        == "dead"
    )


def test_silent_with_no_stock_is_not_dead():
    """Dead stock means capital standing still. A discontinued line at zero is
    not costing anybody anything, so counting it would inflate the one number
    that page exists to report."""
    assert (
        _classify(on_hand=0, daily_rate=0.0, days_since_sale=DEAD_DAYS, growth=None)
        == "healthy"
    )


def test_never_sold_with_stock_is_dead():
    assert (
        _classify(on_hand=10, daily_rate=0.0, days_since_sale=None, growth=None)
        == "dead"
    )


def test_years_of_cover_is_overstocked():
    on_hand = int((OVERSTOCK_COVER_DAYS + 10) * 2)
    assert (
        _classify(on_hand, daily_rate=2.0, days_since_sale=1, growth=None)
        == "overstocked"
    )


def test_growth_below_the_threshold_is_not_growth():
    """Weekly rhythm alone moves a small SKU by ten per cent. Only movement
    above the threshold is reported as a state."""
    # Cover deliberately in the middle of the healthy range. At 1000 units and
    # two a day this reads as overstocked long before growth is consulted, and
    # the test would pass or fail for a reason it is not about.
    on_hand = 100  # 50 days of cover
    below = GROWTH_THRESHOLD - 0.01
    assert (
        _classify(on_hand, daily_rate=2.0, days_since_sale=1, growth=below) == "healthy"
    )
    assert (
        _classify(on_hand, daily_rate=2.0, days_since_sale=1, growth=GROWTH_THRESHOLD)
        == "growing"
    )


# ---------------------------------------------------------------------------
# The workspace filter and the cap
# ---------------------------------------------------------------------------


def test_dead_stock_survives_the_revenue_cap(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """The regression this file exists for.

    A dead product earns nothing, so it sorts last by revenue. If the cap were
    applied before the workspace filter, it would be cut before the filter ever
    saw it and the dead-stock workspace would report an empty, confident zero.
    """
    warehouse = make_warehouse(company)

    earner = make_product(company, name="Sells Constantly")
    make_stock(earner, warehouse, 500)
    sell(earner, warehouse, quantity=40, days_ago=2, unit_price=5000)

    silent = make_product(company, name="Has Not Sold In Months")
    make_stock(silent, warehouse, 80)
    sell(silent, warehouse, quantity=1, days_ago=DEAD_DAYS + 30, unit_price=10)

    data = product_intelligence(db_session, company.id, days=30, workspace_key="dead")

    names = [r["name"] for r in data["products"]]
    assert names == ["Has Not Sold In Months"]
    assert data["workspace"] == "dead"


def test_narrowing_the_list_does_not_narrow_the_kpis(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """A group's size is meaningless without the total it is a share of.

    "13 products" is a fact; "13 of 200" is a decision. So the KPIs and the
    distribution describe the whole catalogue whichever workspace is open.
    """
    warehouse = make_warehouse(company)
    for i in range(4):
        product = make_product(company, name=f"Product {i}")
        make_stock(product, warehouse, 200)
        sell(product, warehouse, quantity=5, days_ago=3)

    silent = make_product(company, name="Silent")
    make_stock(silent, warehouse, 40)

    whole = product_intelligence(db_session, company.id, days=30)
    narrowed = product_intelligence(
        db_session, company.id, days=30, workspace_key="dead"
    )

    assert narrowed["kpis"] == whole["kpis"]
    assert narrowed["distribution"] == whole["distribution"]
    assert len(narrowed["products"]) < len(whole["products"])


def test_an_unknown_workspace_returns_the_whole_catalogue(
    db_session, company, make_product, make_warehouse, make_stock
):
    """Not an empty list. An empty list reads as "nothing matches", which is a
    different claim from "that is not a group"."""
    warehouse = make_warehouse(company)
    for i in range(3):
        make_stock(make_product(company, name=f"P{i}"), warehouse, 10)

    data = product_intelligence(
        db_session, company.id, days=30, workspace_key="not_a_workspace"
    )
    assert len(data["products"]) == 3


def test_stockout_risk_is_ordered_emptiest_first(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """The order is the claim the workspace makes about what matters most."""
    warehouse = make_warehouse(company)

    empty = make_product(company, name="Empty")
    make_stock(empty, warehouse, 0)
    sell(empty, warehouse, quantity=60, days_ago=2)

    thin = make_product(company, name="Thin")
    make_stock(thin, warehouse, 20)
    sell(thin, warehouse, quantity=60, days_ago=2)

    data = product_intelligence(
        db_session, company.id, days=30, workspace_key="at_risk"
    )
    assert [r["name"] for r in data["products"]] == ["Empty", "Thin"]


def test_another_tenants_products_are_not_classified(
    db_session, company, other_company, make_product, make_warehouse, make_stock
):
    warehouse = make_warehouse(company)
    make_stock(make_product(company, name="Ours"), warehouse, 10)

    other_warehouse = make_warehouse(other_company, name="Theirs WH")
    make_stock(make_product(other_company, name="Theirs"), other_warehouse, 10)

    data = product_intelligence(db_session, company.id, days=30)
    assert [r["name"] for r in data["products"]] == ["Ours"]
    assert data["kpis"]["total"] == 1


# ---------------------------------------------------------------------------
# The health score
# ---------------------------------------------------------------------------


def test_a_healthy_product_scores_full_marks_with_no_factors():
    result = _health(
        bucket="healthy", cover=45.0, growth=0.05, margin=0.4, days_since_sale=2
    )
    assert result["score"] == 100
    assert result["factors"] == []
    assert result["band"] == "strong"


def test_every_deduction_is_named():
    """The score is a summary of the factors, not a replacement for them. A
    number nobody can explain is worse than no number, so a deduction that
    moves the score without appearing in the list is a bug."""
    result = _health(
        bucket="critical", cover=0.0, growth=-0.5, margin=0.02, days_since_sale=90
    )
    assert result["score"] == 100 + sum(f["impact"] for f in result["factors"])
    assert len(result["factors"]) == 4
    assert all(f["impact"] < 0 and f["detail"] for f in result["factors"])


def test_the_score_never_goes_below_zero():
    result = _health(
        bucket="critical", cover=0.0, growth=-1.0, margin=0.0, days_since_sale=999
    )
    assert result["score"] >= 0


def test_stock_deductions_are_mutually_exclusive():
    """A product cannot be both out of stock and overstocked. Only one stock
    deduction may ever apply, or the score double-counts one problem."""
    for args in [
        dict(bucket="critical", cover=0.0),
        dict(bucket="healthy", cover=1.0),
        dict(bucket="healthy", cover=OVERSTOCK_COVER_DAYS + 50),
    ]:
        result = _health(growth=None, margin=0.4, days_since_sale=1, **args)
        stock_factors = [
            f
            for f in result["factors"]
            if f["label"] in {"Out of stock", "Low cover", "Overstocked"}
        ]
        assert len(stock_factors) == 1, args


# ---------------------------------------------------------------------------
# The command center
# ---------------------------------------------------------------------------


def test_quiet_months_are_drawn_rather_than_dropped(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """A bar chart with months missing does not show a gap, it closes it.

    The GROUP BY only returns months that have sales, so a product that went
    quiet came back with fewer bars. For a product that is dying, the silence is
    the most important thing on the chart.
    """
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, 100)
    sell(product, warehouse, quantity=5, days_ago=2)
    sell(product, warehouse, quantity=5, days_ago=400)

    data = product_command_center(db_session, company.id, product.id, days=90)

    assert len(data["seasonality"]) == SEASONALITY_MONTHS
    months = [m["month"] for m in data["seasonality"]]
    assert months == sorted(months)
    assert any(m["units"] == 0 for m in data["seasonality"])
    # Exactly one month is in progress, and it is the last one.
    partial = [m for m in data["seasonality"] if m["partial"]]
    assert len(partial) == 1 and partial[0] is data["seasonality"][-1]


def test_the_month_in_progress_cannot_be_the_best_month(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """Letting an unfinished month win produces a "best month on record" that
    quietly changes every few days."""
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, 500)
    sell(product, warehouse, quantity=900, days_ago=0)
    sell(product, warehouse, quantity=100, days_ago=200)

    data = product_command_center(db_session, company.id, product.id, days=90)
    best = data["lifetime"]["best_month"]
    current = datetime.now(timezone.utc).strftime("%Y-%m")
    assert best is not None
    assert best["month"] != current


def test_no_demand_means_no_recommendation(
    db_session, company, make_product, make_warehouse, make_stock
):
    """An EOQ divided by zero demand is a division error, not advice."""
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, 100)

    data = product_command_center(db_session, company.id, product.id, days=90)
    assert data["recommendation"] is None


def test_the_recommendation_states_its_assumptions(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """EOQ is a square root of three inputs. Get one wrong and it is
    confidently wrong, so the inputs travel with the answer."""
    warehouse = make_warehouse(company)
    product = make_product(company, unit_cost=200)
    make_stock(product, warehouse, 300)
    for day in range(1, 30):
        sell(product, warehouse, quantity=4, days_ago=day)

    data = product_command_center(db_session, company.id, product.id, days=90)
    rec = data["recommendation"]

    assert rec["eoq"] > 0
    assert rec["assumptions"]["holding_cost_rate"] == HOLDING_COST_RATE
    assert rec["assumptions"]["annual_demand"] > 0
    # No purchase order carries a delivery date here, so the page must say the
    # lead time was assumed rather than presenting a guess as a measurement.
    assert "assumed" in rec["lead_time_source"]


def test_a_product_from_another_tenant_is_not_found(
    db_session, company, other_company, make_product
):
    theirs = make_product(other_company, name="Not Ours")
    assert product_command_center(db_session, company.id, theirs.id, days=90) is None
