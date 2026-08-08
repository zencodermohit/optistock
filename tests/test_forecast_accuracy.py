"""Recording forecasts and scoring them against what actually sold."""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.modules.analytics.accuracy import (
    accuracy_summary,
    persist_forecast_runs,
    score_due_forecasts,
)
from app.modules.analytics.forecast import run_demand_forecast
from app.modules.analytics.models import ForecastRun


def _forecast_frame(company, product, warehouse, quantity=70):
    return pd.DataFrame(
        [
            {
                "company_id": company.id,
                "warehouse_id": warehouse.id,
                "product_id": product.id,
                "units_sold_in_window": quantity * 4,
                "active_days": 20,
                "avg_daily_sales": quantity / 7,
                "forecast_quantity": quantity,
                "confidence_score": 67,
            }
        ]
    )


@pytest.fixture
def pair(company, make_warehouse, make_product):
    return make_product(company, sku="FC-001"), make_warehouse(company)


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
def test_a_forecast_window_covers_exactly_its_horizon(db_session, company, pair):
    """horizon_end is the LAST day of the window, not the day after it.

    Off by one here would compare a 7-day forecast against 8 days of sales and
    report the model under-predicting by a fixed amount forever -- a bias that
    looks like a modelling problem and is arithmetic.
    """
    product, warehouse = pair
    predicted_at = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    persist_forecast_runs(
        db_session,
        _forecast_frame(company, product, warehouse),
        horizon_days=7,
        predicted_at=predicted_at,
    )
    db_session.flush()

    run = db_session.query(ForecastRun).one()
    assert run.horizon_end == (predicted_at.date() + timedelta(days=6))


def test_a_forecast_is_not_scored_while_its_window_is_still_open(
    db_session, company, pair
):
    product, warehouse = pair
    predicted_at = datetime.now(timezone.utc)

    persist_forecast_runs(
        db_session,
        _forecast_frame(company, product, warehouse),
        horizon_days=7,
        predicted_at=predicted_at,
    )
    db_session.flush()

    assert score_due_forecasts(db_session) == 0
    assert db_session.query(ForecastRun).one().scored_at is None


def test_the_backtest_window_excludes_sales_from_after_the_cutoff(tmp_path):
    """`as_of` must bound the window at BOTH ends.

    Only the lower bound used to move, which is invisible in production -- there
    are no sales from the future -- and silently wrong in any backtest. Set
    eight weeks back it summed eighty-six days of sales and divided by the
    thirty-day window, inflating velocity nearly threefold and making every
    historical forecast roughly double what it should have been.
    """
    now = datetime.now(timezone.utc)
    as_of = now - timedelta(days=30)

    frame = pd.DataFrame(
        [
            # Inside the window that ends at as_of.
            {
                "company_id": "11111111-1111-1111-1111-111111111111",
                "warehouse_id": "22222222-2222-2222-2222-222222222222",
                "product_id": "33333333-3333-3333-3333-333333333333",
                "sale_date": as_of - timedelta(days=5),
                "quantity": 10,
            },
            # After the cutoff: the future, as far as this forecast is concerned.
            {
                "company_id": "11111111-1111-1111-1111-111111111111",
                "warehouse_id": "22222222-2222-2222-2222-222222222222",
                "product_id": "33333333-3333-3333-3333-333333333333",
                "sale_date": as_of + timedelta(days=10),
                "quantity": 500,
            },
        ]
    )
    path = tmp_path / "fact_sales_2026_01_01.parquet"
    frame.to_parquet(path, index=False)

    result = run_demand_forecast(
        data_lake_dir=str(tmp_path), lookback_days=30, horizon_days=7, as_of=as_of
    )

    assert len(result) == 1
    # 10 units over a 30-day window is 0.33/day, so ~2 over 7 days. Had the
    # 500-unit sale leaked in, this would be 119.
    assert int(result.iloc[0]["units_sold_in_window"]) == 10
    assert int(result.iloc[0]["forecast_quantity"]) == 2


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def test_scoring_measures_the_forecast_against_real_sales(
    db_session, company, pair, make_customer, authenticated_client, make_stock
):
    product, warehouse = pair
    make_stock(product, warehouse, quantity=500)
    customer = make_customer(company)

    # A forecast whose window has already closed.
    predicted_at = datetime.now(timezone.utc) - timedelta(days=10)
    persist_forecast_runs(
        db_session,
        _forecast_frame(company, product, warehouse, quantity=12),
        horizon_days=7,
        predicted_at=predicted_at,
    )
    db_session.flush()

    # Sales inside that window. created_at is set explicitly, because the sale
    # is being backdated into the window that was predicted.
    from app.modules.sales.models import Sale, SaleItem

    sale = Sale(
        company_id=company.id,
        customer_id=customer.id,
        source_warehouse_id=warehouse.id,
        status="completed",
        total_amount=200,
        created_at=predicted_at + timedelta(days=2),
    )
    db_session.add(sale)
    db_session.flush()
    db_session.add(
        SaleItem(sale_id=sale.id, product_id=product.id, quantity=8, unit_price=25)
    )
    db_session.flush()

    assert score_due_forecasts(db_session) == 1

    run = db_session.query(ForecastRun).one()
    assert run.actual_quantity == 8
    assert run.absolute_error == 4
    assert run.scored_at is not None


def test_selling_nothing_scores_as_zero_not_as_missing(db_session, company, pair):
    """Absence is a real outcome, and it is the over-prediction case.

    Skipping rows with no sales would drop exactly the forecasts that were most
    wrong, and the reported accuracy would improve every time the model
    hallucinated demand.
    """
    product, warehouse = pair
    persist_forecast_runs(
        db_session,
        _forecast_frame(company, product, warehouse, quantity=40),
        horizon_days=7,
        predicted_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db_session.flush()

    score_due_forecasts(db_session)

    run = db_session.query(ForecastRun).one()
    assert run.actual_quantity == 0
    assert run.absolute_error == 40


def test_scoring_is_not_repeated_on_a_second_pass(db_session, company, pair):
    product, warehouse = pair
    persist_forecast_runs(
        db_session,
        _forecast_frame(company, product, warehouse),
        horizon_days=7,
        predicted_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db_session.flush()

    assert score_due_forecasts(db_session) == 1
    assert score_due_forecasts(db_session) == 0


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def test_nothing_scored_reports_unknown_rather_than_perfect(db_session, company):
    """Zero error would read as a flawless forecast, which is the opposite."""
    summary = accuracy_summary(db_session, company.id)

    assert summary["scored"] == 0
    assert summary["weighted_ape"] is None
    assert summary["mae"] is None


def test_error_is_weighted_by_volume_not_averaged_per_product(
    db_session, company, make_warehouse, make_product
):
    """Textbook MAPE divides by each actual and is dominated by slow movers.

    One product forecast at 100 that sold 90, and one forecast at 2 that sold 1:
    per-product MAPE averages 10% and 100% into 55%. Weighting by units gives
    11/91, about 12% -- which is what a business losing eleven units out of
    ninety-one actually experienced.
    """
    warehouse = make_warehouse(company)
    fast = make_product(company, sku="FAST")
    slow = make_product(company, sku="SLOW")
    now = datetime.now(timezone.utc)

    db_session.add_all(
        [
            ForecastRun(
                company_id=company.id,
                product_id=fast.id,
                warehouse_id=warehouse.id,
                horizon_days=7,
                forecast_quantity=100,
                avg_daily_sales=14,
                confidence_score=90,
                predicted_at=now - timedelta(days=10),
                horizon_end=(now - timedelta(days=4)).date(),
                actual_quantity=90,
                absolute_error=10,
                scored_at=now,
            ),
            ForecastRun(
                company_id=company.id,
                product_id=slow.id,
                warehouse_id=warehouse.id,
                horizon_days=7,
                forecast_quantity=2,
                avg_daily_sales=0.3,
                confidence_score=10,
                predicted_at=now - timedelta(days=10),
                horizon_end=(now - timedelta(days=4)).date(),
                actual_quantity=1,
                absolute_error=1,
                scored_at=now,
            ),
        ]
    )
    db_session.flush()

    summary = accuracy_summary(db_session, company.id)

    assert summary["scored"] == 2
    assert summary["weighted_ape"] == pytest.approx(11 / 91 * 100, rel=1e-3)
    assert summary["mae"] == pytest.approx(5.5)


def test_accuracy_is_scoped_to_the_callers_company(
    authenticated_client, db_session, other_company, make_warehouse, make_product
):
    warehouse = make_warehouse(other_company)
    product = make_product(other_company)
    now = datetime.now(timezone.utc)

    db_session.add(
        ForecastRun(
            company_id=other_company.id,
            product_id=product.id,
            warehouse_id=warehouse.id,
            horizon_days=7,
            forecast_quantity=50,
            avg_daily_sales=7,
            confidence_score=80,
            predicted_at=now - timedelta(days=10),
            horizon_end=(now - timedelta(days=4)).date(),
            actual_quantity=10,
            absolute_error=40,
            scored_at=now,
        )
    )
    db_session.commit()

    body = authenticated_client.get("/api/v1/insights/accuracy").json()

    assert body["summary"]["scored"] == 0
    assert body["worst"] == []
