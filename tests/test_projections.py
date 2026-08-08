"""The daily metrics read model: incremental updates, and the rebuild."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.modules.analytics.projection_models import DailyMetric
from app.modules.analytics.projections import (
    apply_movement,
    apply_sale,
    rebuild_daily_metrics,
    recent_metrics,
)
from app.modules.events import types as event_types
from app.workers.consumers import dispatch

import app.modules.analytics.handlers  # noqa: F401,E402


def _row(db_session, company, day):
    return (
        db_session.query(DailyMetric)
        .filter(DailyMetric.company_id == company.id, DailyMetric.metric_date == day)
        .first()
    )


TODAY = date(2026, 8, 8)


# ---------------------------------------------------------------------------
# Incremental
# ---------------------------------------------------------------------------
def test_the_first_sale_of_a_day_creates_the_row(db_session, company):
    apply_sale(
        db_session,
        company.id,
        TODAY,
        {"total_amount": 1500.50, "unit_count": 7},
    )
    db_session.flush()

    row = _row(db_session, company, TODAY)
    assert row.revenue == Decimal("1500.50")
    assert row.orders == 1
    assert row.units_sold == 7


def test_further_sales_add_to_the_same_day(db_session, company):
    """An upsert that adds, not a read-modify-write that overwrites.

    Two consumer replicas handling two sales at the same instant would both read
    the same starting total and both write their own, losing one. Letting
    Postgres do the addition makes the race impossible rather than unlikely.
    """
    for amount in (100, 250, 75):
        apply_sale(
            db_session, company.id, TODAY, {"total_amount": amount, "unit_count": 2}
        )
    db_session.flush()

    row = _row(db_session, company, TODAY)
    assert row.revenue == Decimal("425")
    assert row.orders == 3
    assert row.units_sold == 6


def test_only_inbound_movement_counts_as_received(db_session, company):
    """Outbound is already counted as units_sold.

    Counting a deduction under a second name would make the two figures
    contradict each other on the same screen.
    """
    apply_movement(db_session, company.id, TODAY, {"quantity_change": 40})
    apply_movement(db_session, company.id, TODAY, {"quantity_change": -12})
    db_session.flush()

    row = _row(db_session, company, TODAY)
    assert row.stock_movements == 2
    assert row.units_received == 40


def test_the_event_decides_the_day_not_the_clock(db_session, company):
    """A consumer catching up must not file yesterday's events under today.

    After an outage the backlog drains at once. Using date.today() would move
    revenue between days, and the day it moved from would silently understate.
    """
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).replace(microsecond=0)
    dispatch(
        db_session,
        {
            "event_id": "11111111-1111-1111-1111-111111111111",
            "company_id": str(company.id),
            "event_type": event_types.SALE_COMPLETED,
            "aggregate_type": "sale",
            "aggregate_id": "22222222-2222-2222-2222-222222222222",
            "occurred_at": yesterday.isoformat(),
            "payload": {"total_amount": 900, "unit_count": 3},
        },
    )
    db_session.flush()

    assert _row(db_session, company, yesterday.date()).revenue == Decimal("900")
    assert _row(db_session, company, datetime.now(timezone.utc).date()) is None


# ---------------------------------------------------------------------------
# Rebuild
# ---------------------------------------------------------------------------
@pytest.fixture
def a_sale(
    authenticated_client,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company, unit_cost=10, selling_price=25)
    make_stock(product, warehouse, quantity=100)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [{"product_id": str(product.id), "quantity": 4, "unit_price": 25}],
        },
    )
    assert response.status_code in (200, 201)
    return response.json()


def test_rebuild_reproduces_what_the_handlers_would_have_written(
    db_session, company, a_sale
):
    """The two write paths must agree, or the dashboard changes after a rebuild.

    This is the property that makes the incremental path safe to get wrong: if
    a handler drifts, recomputing from the source tables repairs it.
    """
    rebuild_daily_metrics(db_session, company_id=company.id)
    db_session.flush()

    today = datetime.now(timezone.utc).date()
    row = _row(db_session, company, today)
    assert row is not None
    assert row.orders == 1
    assert row.units_sold == 4
    assert row.revenue == Decimal("100.00")


def test_rebuild_removes_days_the_source_no_longer_produces(db_session, company):
    """Deleting the range first, rather than upserting over it.

    An upsert would leave orphan days behind -- a row nothing can produce is a
    row nobody will ever notice is wrong.
    """
    stale = date(2020, 1, 1)
    apply_sale(db_session, company.id, stale, {"total_amount": 999, "unit_count": 1})
    db_session.flush()
    assert _row(db_session, company, stale) is not None

    rebuild_daily_metrics(db_session, company_id=company.id)
    db_session.flush()

    assert _row(db_session, company, stale) is None


def test_rebuild_leaves_other_tenants_alone(db_session, company, other_company):
    apply_sale(
        db_session, other_company.id, TODAY, {"total_amount": 500, "unit_count": 5}
    )
    db_session.flush()

    rebuild_daily_metrics(db_session, company_id=company.id)
    db_session.flush()

    assert _row(db_session, other_company, TODAY) is not None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def test_quiet_days_are_returned_as_zero_not_skipped(db_session, company):
    """A chart that omits empty days draws a line across them.

    That reports trading which never happened, and it silently compresses the
    x-axis so the shape of the series is wrong too.
    """
    today = datetime.now(timezone.utc).date()
    apply_sale(db_session, company.id, today, {"total_amount": 10, "unit_count": 1})
    db_session.flush()

    series = recent_metrics(db_session, company.id, days=7)

    assert len(series) == 7
    assert [s["date"] for s in series] == [
        (today - timedelta(days=6 - i)).isoformat() for i in range(7)
    ]
    assert series[-1]["revenue"] == 10.0
    assert all(s["revenue"] == 0 for s in series[:-1])


def test_overview_endpoint_reports_the_stock_position_live(
    authenticated_client,
    company,
    make_warehouse,
    make_product,
    make_stock,
    db_session,
):
    warehouse = make_warehouse(company)
    healthy = make_product(company, sku="OV-1", unit_cost=10)
    low = make_product(company, sku="OV-2", unit_cost=5)
    empty = make_product(company, sku="OV-3", unit_cost=7)

    make_stock(healthy, warehouse, quantity=100)
    low_line = make_stock(low, warehouse, quantity=3)
    low_line.reorder_point = 10
    make_stock(empty, warehouse, quantity=0)
    db_session.commit()

    body = authenticated_client.get("/api/v1/dashboard/overview").json()

    stock = body["stock"]
    assert stock["lines"] == 3
    assert stock["low"] == 1
    assert stock["out"] == 1
    # Valued at cost: 100*10 + 3*5 + 0*7. Retail value would count profit that
    # has not been earned.
    assert stock["value_at_cost"] == pytest.approx(1015.0)


def test_overview_is_scoped_to_the_callers_company(
    authenticated_client, db_session, other_company
):
    apply_sale(
        db_session,
        other_company.id,
        datetime.now(timezone.utc).date(),
        {"total_amount": 99999, "unit_count": 999},
    )
    db_session.commit()

    body = authenticated_client.get("/api/v1/dashboard/overview").json()

    assert body["trading"]["revenue"] == 0
    assert body["stock"]["lines"] == 0
