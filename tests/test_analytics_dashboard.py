"""The Analytics read model.

Three of the figures on that page are derived rather than stored, which makes
them exactly the kind of number that drifts without anyone noticing. These tests
pin the definitions down.

The first one is a regression. The risk bands originally used an exclusive
`lower < days` for every band, so a line sitting at exactly zero days fell into
none of them -- the most urgent column on the page read zero while shelves were
already empty. It was found by reading a live response, not by a test, which is
why there is a test now.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.dashboard import DEAD_STOCK_DAYS, _health, analytics
from app.modules.sales.models import Sale, SaleItem


@pytest.fixture
def sell(db_session, company, make_customer):
    customer = make_customer(company)

    def _sell(product, warehouse, quantity, days_ago=1):
        sale = Sale(
            company_id=company.id,
            customer_id=customer.id,
            source_warehouse_id=warehouse.id,
            status="completed",
            total_amount=quantity * 100,
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
        db_session.add(sale)
        db_session.flush()
        db_session.add(
            SaleItem(
                sale_id=sale.id,
                product_id=product.id,
                quantity=quantity,
                unit_price=100,
            )
        )
        db_session.flush()

    return _sell


# ---------------------------------------------------------------------------
# Risk bands
# ---------------------------------------------------------------------------
def test_an_out_of_stock_line_lands_in_the_critical_band(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """The regression. A line at exactly zero days must be counted somewhere,
    and the somewhere is the most urgent band."""
    warehouse = make_warehouse(company)
    empty = make_product(company, sku="BAND-OUT")
    make_stock(empty, warehouse, quantity=0)
    # It has to have sold, or the model reports it as unmeasured rather than
    # urgent -- which is a different and equally deliberate answer.
    for day in range(1, 11):
        sell(empty, warehouse, 5, days_ago=day)
    db_session.commit()

    data = analytics(db_session, company.id, days=30)
    bands = {b["key"]: b["count"] for b in data["risk_bands"]}

    assert bands["critical"] >= 1
    assert data["kpis"]["critical"] == bands["critical"]


def test_the_bands_do_not_double_count(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """Adjacent bands share a boundary; a line on it belongs to exactly one."""
    warehouse = make_warehouse(company)
    for i, (sku, qty) in enumerate([("B1", 0), ("B2", 20), ("B3", 300)]):
        product = make_product(company, sku=f"BAND-{sku}")
        make_stock(product, warehouse, quantity=qty)
        for day in range(1, 11):
            sell(product, warehouse, 6, days_ago=day)
    db_session.commit()

    data = analytics(db_session, company.id, days=30)
    total_banded = sum(b["count"] for b in data["risk_bands"])

    assert total_banded == 3


def test_at_risk_excludes_the_comfortable_band(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    warehouse = make_warehouse(company)
    product = make_product(company, sku="COMFY-1")
    make_stock(product, warehouse, quantity=5000)
    for day in range(1, 11):
        sell(product, warehouse, 2, days_ago=day)
    db_session.commit()

    data = analytics(db_session, company.id, days=30)
    low = next(b for b in data["risk_bands"] if b["key"] == "low")

    assert low["count"] >= 1
    assert data["kpis"]["at_risk"] == sum(
        b["count"] for b in data["risk_bands"] if b["key"] != "low"
    )


# ---------------------------------------------------------------------------
# Health score
# ---------------------------------------------------------------------------
def test_a_clean_warehouse_scores_full_marks():
    assert _health(lines=100, out=0, low=0, alerts=0)["score"] == 100


def test_each_penalty_is_weighted_as_documented():
    """The formula is printed on the page, so it had better be the one that
    runs. Out-of-stock costs more than twice what below-reorder costs, because
    it loses the sale rather than threatening it."""
    out_only = _health(lines=100, out=10, low=0, alerts=0)
    low_only = _health(lines=100, out=0, low=10, alerts=0)

    assert out_only["out_penalty"] == 6.0  # 60 x 0.10
    assert low_only["low_penalty"] == 2.5  # 25 x 0.10
    assert out_only["score"] == 94
    assert low_only["score"] == 98


def test_the_alert_penalty_is_capped(db_session):
    """Twenty alerts is not four times worse than five -- past a point it is
    the same message repeated."""
    five = _health(lines=100, out=0, low=0, alerts=5)
    fifty = _health(lines=100, out=0, low=0, alerts=50)

    assert five["alert_penalty"] == 15.0
    assert fifty["alert_penalty"] == 15.0


def test_a_warehouse_with_no_stock_has_no_score():
    """Null, not 100. An empty warehouse is unmeasured, not perfect."""
    assert _health(lines=0, out=0, low=0, alerts=0)["score"] is None


def test_a_wholly_empty_warehouse_scores_its_worst_realistic_case():
    """Every line out of stock and alerts saturated: 100 − 60 − 15 = 25.

    It does not reach zero, and it cannot: a line is either OUT or BELOW its
    reorder point, never both, so the two stock penalties can never both max
    out. The clamp in _health is defensive rather than reachable, which is
    worth knowing before someone "fixes" the arithmetic to make 0 possible.
    """
    assert _health(lines=10, out=10, low=0, alerts=50)["score"] == 25


# ---------------------------------------------------------------------------
# Dead inventory
# ---------------------------------------------------------------------------
def test_dead_stock_is_measured_per_warehouse_not_per_product(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """A product selling in one site and sitting still in another is dead in
    the second. Keyed any coarser and that is invisible."""
    product = make_product(company, sku="SPLIT-DEAD")
    product.unit_cost = 10
    busy = make_warehouse(company, name="Busy")
    idle = make_warehouse(company, name="Idle")
    make_stock(product, busy, quantity=50)
    make_stock(product, idle, quantity=50)
    sell(product, busy, 5, days_ago=2)
    db_session.commit()

    data = analytics(db_session, company.id, days=30)

    # Only the idle site's line counts, and it is valued at cost.
    assert data["kpis"]["dead_lines"] == 1
    assert data["kpis"]["dead_value"] == 500.0


def test_a_line_that_sold_inside_the_window_is_not_dead(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    product = make_product(company, sku="ALIVE-1")
    product.unit_cost = 10
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=40)
    sell(product, warehouse, 1, days_ago=DEAD_STOCK_DAYS - 5)
    db_session.commit()

    assert analytics(db_session, company.id, days=30)["kpis"]["dead_lines"] == 0


def test_an_empty_line_is_not_dead_stock(
    db_session, company, make_product, make_warehouse, make_stock
):
    """Dead stock is capital sitting still. A line at zero has no capital in
    it -- it is a stockout, which the risk bands already report."""
    product = make_product(company, sku="EMPTY-DEAD")
    product.unit_cost = 10
    make_stock(product, make_warehouse(company), quantity=0)
    db_session.commit()

    assert analytics(db_session, company.id, days=30)["kpis"]["dead_lines"] == 0


# ---------------------------------------------------------------------------
# Composition and scoping
# ---------------------------------------------------------------------------
def test_inventory_health_buckets_sum_to_the_total(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """Three parts of one whole. If they stop adding up, the bar lies."""
    warehouse = make_warehouse(company)
    for sku, qty, sold in [("H1", 100, True), ("H2", 9000, True), ("H3", 60, False)]:
        product = make_product(company, sku=f"HEALTH-{sku}")
        product.unit_cost = 10
        make_stock(product, warehouse, quantity=qty)
        if sold:
            for day in range(1, 11):
                sell(product, warehouse, 4, days_ago=day)
    db_session.commit()

    health = analytics(db_session, company.id, days=30)["inventory_health"]
    parts = health["healthy"] + health["excess"] + health["dead"]

    assert parts == pytest.approx(health["total"], abs=0.01)


def test_the_warehouse_filter_narrows_every_figure(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    a = make_warehouse(company, name="Site A")
    b = make_warehouse(company, name="Site B")
    for warehouse, sku in ((a, "FA"), (b, "FB")):
        product = make_product(company, sku=f"FILT-{sku}")
        product.unit_cost = 10
        make_stock(product, warehouse, quantity=100)
        sell(product, warehouse, 3, days_ago=2)
    db_session.commit()

    everything = analytics(db_session, company.id, days=30)
    just_a = analytics(db_session, company.id, days=30, warehouse_id=a.id)

    assert len(everything["warehouse_performance"]) == 2
    assert [w["name"] for w in just_a["warehouse_performance"]] == ["Site A"]
    assert just_a["kpis"]["inventory_value"] < everything["kpis"]["inventory_value"]


def test_analytics_is_scoped_to_the_company(
    db_session, company, other_company, make_product, make_warehouse, make_stock
):
    for owner, sku, site in (
        (company, "MINE-AN", "Mine Site"),
        (other_company, "THEIRS-AN", "Their Site"),
    ):
        product = make_product(owner, sku=sku)
        product.unit_cost = 10
        make_stock(product, make_warehouse(owner, name=site), quantity=100)
    db_session.commit()

    mine = analytics(db_session, company.id, days=30)
    theirs = analytics(db_session, other_company.id, days=30)

    assert mine["kpis"]["stock_lines"] == 1
    assert theirs["kpis"]["stock_lines"] == 1
    assert {w["name"] for w in mine["warehouse_performance"]}.isdisjoint(
        {w["name"] for w in theirs["warehouse_performance"]}
    )


def test_the_assumptions_travel_with_the_figures(db_session, company):
    """Every derived number states its definition, because a figure whose
    definition is hidden is a figure nobody can argue with."""
    data = analytics(db_session, company.id, days=30)

    assert data["assumptions"]["dead_stock_days"] == DEAD_STOCK_DAYS
    assert "average inventory" in data["assumptions"]["turnover_note"]
    assert "out of stock" in data["assumptions"]["health_formula"]


def test_the_endpoint_answers(authenticated_client):
    response = authenticated_client.get("/api/v1/dashboard/analytics?days=30")

    assert response.status_code == 200
    body = response.json()
    for key in (
        "kpis",
        "revenue_trend",
        "warehouse_performance",
        "risk_bands",
        "inventory_health",
        "critical_alerts",
        "assumptions",
    ):
        assert key in body, key


# ---------------------------------------------------------------------------
# The warehouse filter reaches the trend
#
# It did not. `daily_metrics` is keyed on (company_id, metric_date) with no
# warehouse dimension, so revenue, the change percentage and the whole trend
# chart stayed company-wide while every other figure on the page narrowed.
# Nothing errored -- it just quietly showed one site's stock beside the whole
# company's revenue.
# ---------------------------------------------------------------------------
def test_filtering_by_site_narrows_the_revenue_trend(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    a = make_warehouse(company, name="Trend A")
    b = make_warehouse(company, name="Trend B")
    pa = make_product(company, sku="TREND-A")
    pb = make_product(company, sku="TREND-B")
    make_stock(pa, a, quantity=500)
    make_stock(pb, b, quantity=500)
    # Twice as much trade through A as through B.
    for day in range(1, 6):
        sell(pa, a, 20, days_ago=day)
        sell(pb, b, 10, days_ago=day)
    db_session.commit()

    just_a = analytics(db_session, company.id, days=30, warehouse_id=a.id)
    just_b = analytics(db_session, company.id, days=30, warehouse_id=b.id)

    a_rev = sum(p["revenue"] for p in just_a["revenue_trend"])
    b_rev = sum(p["revenue"] for p in just_b["revenue_trend"])

    assert a_rev > 0 and b_rev > 0
    assert a_rev != b_rev, "both sites returned the same trend"
    assert a_rev == pytest.approx(b_rev * 2, rel=0.01)
    # And the KPI agrees with the chart beside it.
    assert just_a["kpis"]["revenue"] == pytest.approx(a_rev, abs=0.01)

    # Deliberately NOT compared against the unfiltered figure. That path reads
    # daily_metrics, which the event consumers maintain and which no test runs,
    # so it is empty here. That is not a flaw in this test -- it is the same
    # asymmetry the page now labels: unfiltered reads a projection that can lag,
    # filtered reads the sales themselves.


def test_the_trend_names_which_query_answered_it(db_session, company, make_warehouse):
    """The two paths can disagree -- the projection is maintained by background
    consumers and can lag -- so the page says which one it used."""
    warehouse = make_warehouse(company)
    db_session.commit()

    assert analytics(db_session, company.id, days=30)["trend_source"] == "projection"
    assert (
        analytics(db_session, company.id, days=30, warehouse_id=warehouse.id)[
            "trend_source"
        ]
        == "sales"
    )


def test_the_filtered_trend_still_fills_quiet_days(
    db_session, company, make_product, make_warehouse, make_stock, sell
):
    """A chart that skips quiet days draws a straight line across them and
    reports trading that never happened."""
    warehouse = make_warehouse(company)
    product = make_product(company, sku="GAPS-1")
    make_stock(product, warehouse, quantity=200)
    sell(product, warehouse, 5, days_ago=2)
    db_session.commit()

    trend = analytics(db_session, company.id, days=14, warehouse_id=warehouse.id)[
        "revenue_trend"
    ]

    assert len(trend) == 14
    assert sum(1 for p in trend if p["revenue"] == 0) == 13
