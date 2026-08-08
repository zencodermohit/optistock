"""End-to-end tests for the nightly analytics chain.

Sales rows -> ETL -> Parquet -> ABC / forecast -> persisted results.

Every piece of this existed and worked in isolation before; none of it was
connected to anything. These tests exercise the whole chain, and in particular
pin the two properties that were most at risk once it WAS connected:

  * tenant correctness — the data lake mixes all companies into one file
  * arithmetic honesty — velocity must divide by the window, not by active days
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.modules.analytics.abc_analysis import run_abc_analysis
from app.modules.analytics.forecast import run_demand_forecast
from app.modules.analytics.persistence import (
    PIPELINE_SOURCE,
    persist_abc_classes,
    persist_reorder_recommendations,
)
from app.modules.products.models import Product
from app.modules.recommendations.models import Recommendation
from app.modules.sales.models import Sale, SaleItem
from etl.extract import extract_sales_data
from etl.load import load_to_data_lake
from etl.pipeline import run_nightly_etl
from etl.transform import transform_sales_to_star_schema


@pytest.fixture
def lake(tmp_path):
    """An isolated data lake directory per test."""
    return str(tmp_path / "data_lake")


@pytest.fixture
def record_sale(db_session, make_customer):
    """Insert a completed sale line directly, at a chosen date."""
    customers = {}

    def _record(company, warehouse, product, quantity, unit_price=10.0, days_ago=0):
        # sales.customer_id is NOT NULL; reuse one customer per tenant.
        if company.id not in customers:
            customers[company.id] = make_customer(company)

        sale = Sale(
            company_id=company.id,
            customer_id=customers[company.id].id,
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
        db_session.commit()
        return sale

    return _record


# ---------------------------------------------------------------------------
# ETL
# ---------------------------------------------------------------------------
def test_extract_carries_the_tenant_key(
    db_session, company, make_warehouse, make_product, make_customer, record_sale
):
    """Without company_id the lake cannot attribute anything to a tenant."""
    warehouse = make_warehouse(company)
    product = make_product(company)
    record_sale(company, warehouse, product, quantity=3)

    sales = extract_sales_data(engine=db_session.get_bind())

    assert "company_id" in sales.columns
    assert "warehouse_id" in sales.columns
    assert str(sales.iloc[0]["company_id"]) == str(company.id)


def test_transform_rejects_a_fact_table_missing_the_tenant_key():
    """A silent schema regression upstream must fail here, not downstream."""
    sales = pd.DataFrame(
        [
            {
                "product_id": "p1",
                "quantity": 1,
                "unit_price": 2.0,
                "sale_date": "2026-01-01",
            }
        ]
    )
    products = pd.DataFrame([{"product_id": "p1", "unit_cost": 1.0}])

    with pytest.raises(ValueError, match="company_id"):
        transform_sales_to_star_schema(sales, products)


def test_load_creates_the_directory_if_absent(lake):
    """A fresh container or wiped volume must not break the first nightly run."""
    df = pd.DataFrame([{"company_id": "c1", "quantity": 1}])

    path = load_to_data_lake(df, "fact_sales", data_lake_dir=lake)

    assert pd.read_parquet(path).equals(df)


def test_pipeline_reraises_instead_of_reporting_false_success(monkeypatch, lake):
    """The old pipeline logged failures and returned normally, so the scheduler
    recorded a success and nobody learned the dashboards had gone stale."""

    def boom(*_args, **_kwargs):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr("etl.pipeline.extract_sales_data", boom)

    with pytest.raises(RuntimeError, match="database unreachable"):
        run_nightly_etl(data_lake_dir=lake)


def test_full_etl_writes_a_readable_fact_table(
    db_session, company, make_warehouse, make_product, record_sale, lake
):
    warehouse = make_warehouse(company)
    product = make_product(company, unit_cost=4, selling_price=10)
    record_sale(company, warehouse, product, quantity=5, unit_price=10.0)

    path = run_nightly_etl(engine=db_session.get_bind(), data_lake_dir=lake)

    fact = pd.read_parquet(path)
    assert len(fact) == 1
    assert fact.iloc[0]["total_revenue"] == 50.0
    assert fact.iloc[0]["profit_margin"] == 30.0  # 50 revenue - 20 cost

    # Identifiers must survive the Parquet round trip as strings. Left as UUID
    # objects they return as bytes and blow up against a Postgres uuid column.
    assert fact.iloc[0]["company_id"] == str(company.id)
    assert fact.iloc[0]["product_id"] == str(product.id)
    assert isinstance(fact.iloc[0]["warehouse_id"], str)


# ---------------------------------------------------------------------------
# Forecast arithmetic
# ---------------------------------------------------------------------------
def _fact_row(company_id, warehouse_id, product_id, quantity, days_ago, revenue=None):
    return {
        "company_id": company_id,
        "warehouse_id": warehouse_id,
        "product_id": product_id,
        "quantity": quantity,
        "sale_date": datetime.now(timezone.utc) - timedelta(days=days_ago),
        "total_revenue": revenue if revenue is not None else quantity * 10.0,
    }


def test_velocity_divides_by_the_window_not_by_active_days(lake):
    """The original bug: 10 units on ONE day of a 30-day window scored 10/day.

    True velocity is 10/30 = 0.333/day, so a 7-day forecast is 2 units, not 70.
    """
    load_to_data_lake(
        pd.DataFrame([_fact_row("c1", "w1", "p1", quantity=10, days_ago=3)]),
        "fact_sales",
        data_lake_dir=lake,
    )

    result = run_demand_forecast(data_lake_dir=lake, lookback_days=30, horizon_days=7)

    row = result.iloc[0]
    assert row["units_sold_in_window"] == 10
    assert row["active_days"] == 1
    assert row["avg_daily_sales"] == pytest.approx(10 / 30)
    assert row["forecast_quantity"] == 2  # round(0.333 * 7)


def test_forecast_ignores_sales_outside_the_lookback_window(lake):
    load_to_data_lake(
        pd.DataFrame(
            [
                _fact_row("c1", "w1", "p1", quantity=5, days_ago=2),
                _fact_row("c1", "w1", "p1", quantity=999, days_ago=400),
            ]
        ),
        "fact_sales",
        data_lake_dir=lake,
    )

    result = run_demand_forecast(data_lake_dir=lake, lookback_days=30, horizon_days=7)

    assert result.iloc[0]["units_sold_in_window"] == 5


def test_forecast_separates_warehouses(lake):
    """A reorder suggestion must name the location, so grouping includes it."""
    load_to_data_lake(
        pd.DataFrame(
            [
                _fact_row("c1", "w1", "p1", quantity=30, days_ago=1),
                _fact_row("c1", "w2", "p1", quantity=60, days_ago=1),
            ]
        ),
        "fact_sales",
        data_lake_dir=lake,
    )

    result = run_demand_forecast(data_lake_dir=lake, lookback_days=30, horizon_days=7)

    by_warehouse = dict(zip(result["warehouse_id"], result["units_sold_in_window"]))
    assert by_warehouse == {"w1": 30, "w2": 60}


def test_confidence_rises_with_more_days_of_evidence(lake):
    steady = [_fact_row("c1", "w1", "steady", 1, days_ago=d) for d in range(1, 25)]
    spiky = [_fact_row("c1", "w1", "spiky", 24, days_ago=1)]
    load_to_data_lake(pd.DataFrame(steady + spiky), "fact_sales", data_lake_dir=lake)

    result = run_demand_forecast(
        data_lake_dir=lake, lookback_days=30, horizon_days=7
    ).set_index("product_id")

    # Same total units, very different evidence behind them.
    assert result.loc["steady", "units_sold_in_window"] == 24
    assert result.loc["spiky", "units_sold_in_window"] == 24
    assert (
        result.loc["steady", "confidence_score"]
        > result.loc["spiky", "confidence_score"]
    )


def test_analytics_return_empty_frames_when_the_lake_is_empty(lake):
    assert run_demand_forecast(data_lake_dir=lake).empty
    assert run_abc_analysis(data_lake_dir=lake).empty


def test_a_pre_tenant_key_parquet_file_is_skipped_not_fatal(lake):
    """The lake accumulates history. A file written before company_id existed
    must not permanently break the nightly job with a bare KeyError."""
    load_to_data_lake(
        pd.DataFrame(
            [
                {"product_id": "p1", "quantity": 3, "total_revenue": 30.0}
            ]  # no company_id
        ),
        "fact_sales",
        data_lake_dir=lake,
    )

    assert run_abc_analysis(data_lake_dir=lake).empty
    assert run_demand_forecast(data_lake_dir=lake).empty


def test_a_usable_file_is_preferred_over_a_stale_one(lake, tmp_path):
    """Skipping the stale file must not mean skipping analytics altogether."""
    import os
    import time

    os.makedirs(lake, exist_ok=True)
    pd.DataFrame(
        [{"product_id": "old", "quantity": 1, "total_revenue": 10.0}]
    ).to_parquet(os.path.join(lake, "fact_sales_2020_01_01.parquet"), index=False)
    time.sleep(0.01)
    pd.DataFrame([_fact_row("c1", "w1", "current", 5, 1, revenue=500.0)]).to_parquet(
        os.path.join(lake, "fact_sales_2026_01_01.parquet"), index=False
    )

    result = run_abc_analysis(data_lake_dir=lake)

    assert list(result["product_id"]) == ["current"]


# ---------------------------------------------------------------------------
# ABC classification
# ---------------------------------------------------------------------------
def test_textbook_pareto_split(lake):
    """80 / 15 / 5 revenue split must land as A / B / C."""
    load_to_data_lake(
        pd.DataFrame(
            [
                _fact_row("c1", "w1", "top", 1, 1, revenue=80),
                _fact_row("c1", "w1", "middle", 1, 1, revenue=15),
                _fact_row("c1", "w1", "tail", 1, 1, revenue=5),
            ]
        ),
        "fact_sales",
        data_lake_dir=lake,
    )

    result = run_abc_analysis(data_lake_dir=lake).set_index("product_id")

    assert result.loc["top", "abc_class"] == "A"
    assert result.loc["middle", "abc_class"] == "B"
    assert result.loc["tail", "abc_class"] == "C"


def test_a_dominant_product_is_class_a_not_class_c(lake):
    """Regression: classifying on the cumulative percentage AFTER the item meant
    a product worth 99% of revenue was judged by its own share and labelled C."""
    load_to_data_lake(
        pd.DataFrame(
            [
                _fact_row("c1", "w1", "dominant", 1, 1, revenue=10_000),
                _fact_row("c1", "w1", "scrap", 1, 1, revenue=100),
            ]
        ),
        "fact_sales",
        data_lake_dir=lake,
    )

    result = run_abc_analysis(data_lake_dir=lake).set_index("product_id")

    assert result.loc["dominant", "abc_class"] == "A"
    assert result.loc["scrap", "abc_class"] == "C"


def test_abc_classes_are_ranked_within_each_tenant(lake):
    """Ranking globally would push a small tenant's entire catalogue into C."""
    load_to_data_lake(
        pd.DataFrame(
            [
                # Big tenant
                _fact_row("big", "w1", "big-star", 1, 1, revenue=10_000),
                _fact_row("big", "w1", "big-tail", 1, 1, revenue=100),
                # Small tenant — its best seller is tiny next to the big tenant's
                _fact_row("small", "w1", "small-star", 1, 1, revenue=90),
                _fact_row("small", "w1", "small-tail", 1, 1, revenue=1),
            ]
        ),
        "fact_sales",
        data_lake_dir=lake,
    )

    result = run_abc_analysis(data_lake_dir=lake).set_index("product_id")

    assert result.loc["big-star", "abc_class"] == "A"
    # Judged against its OWN tenant's revenue, not the platform's.
    assert result.loc["small-star", "abc_class"] == "A"
    assert result.loc["small-tail", "abc_class"] == "C"


# ---------------------------------------------------------------------------
# Persistence — the wire that was missing
# ---------------------------------------------------------------------------
def test_abc_results_are_written_to_the_product_row(db_session, company, make_product):
    product = make_product(company)
    abc_df = pd.DataFrame(
        [
            {
                "company_id": company.id,
                "product_id": product.id,
                "total_revenue": 500.0,
                "cumulative_percent": 0.5,
                "abc_class": "A",
            }
        ]
    )

    assert persist_abc_classes(db_session, abc_df) == 1

    db_session.expire_all()
    stored = db_session.query(Product).filter(Product.id == product.id).one()
    assert stored.abc_class == "A"
    assert stored.abc_calculated_at is not None


def test_abc_persistence_refuses_to_write_across_tenants(
    db_session, company, other_company, make_product
):
    """The fact table holds every tenant's rows; a mismatched company_id must not
    write one company's analysis onto another company's catalogue."""
    foreign_product = make_product(other_company)
    abc_df = pd.DataFrame(
        [
            {
                "company_id": company.id,  # wrong tenant for this product
                "product_id": foreign_product.id,
                "total_revenue": 500.0,
                "cumulative_percent": 0.1,
                "abc_class": "A",
            }
        ]
    )

    assert persist_abc_classes(db_session, abc_df) == 0

    db_session.expire_all()
    assert (
        db_session.query(Product)
        .filter(Product.id == foreign_product.id)
        .one()
        .abc_class
        is None
    )


def _forecast_row(company, warehouse, product, forecast_quantity):
    return {
        "company_id": company.id,
        "warehouse_id": warehouse.id,
        "product_id": product.id,
        "units_sold_in_window": forecast_quantity * 4,
        "active_days": 12,
        "avg_daily_sales": forecast_quantity / 7,
        "forecast_quantity": forecast_quantity,
        "confidence_score": 40,
    }


def test_forecast_becomes_a_reorder_recommendation(
    db_session, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=10)

    created = persist_reorder_recommendations(
        db_session,
        pd.DataFrame(
            [_forecast_row(company, warehouse, product, forecast_quantity=50)]
        ),
    )

    assert created == 1
    rec = db_session.query(Recommendation).one()
    assert rec.suggested_action == "reorder"
    # Net of stock already on hand: 50 forecast - 10 on hand.
    assert rec.suggested_quantity == 40
    assert rec.source == PIPELINE_SOURCE
    assert rec.evidence["quantity_on_hand"] == 10
    assert "shortfall of 40" in rec.business_reasoning


def test_no_recommendation_when_stock_already_covers_the_forecast(
    db_session, company, make_warehouse, make_product, make_stock
):
    """Suggesting a reorder for a well-stocked product is noise, and noise is how
    a recommendations feed gets ignored."""
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=500)

    created = persist_reorder_recommendations(
        db_session,
        pd.DataFrame(
            [_forecast_row(company, warehouse, product, forecast_quantity=50)]
        ),
    )

    assert created == 0
    assert db_session.query(Recommendation).count() == 0


def test_rerunning_replaces_rather_than_duplicates(
    db_session, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=0)

    frame = pd.DataFrame(
        [_forecast_row(company, warehouse, product, forecast_quantity=20)]
    )
    persist_reorder_recommendations(db_session, frame)
    persist_reorder_recommendations(db_session, frame)
    persist_reorder_recommendations(db_session, frame)

    assert db_session.query(Recommendation).count() == 1


def test_rerunning_does_not_delete_manually_created_recommendations(
    db_session, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=0)

    db_session.add(
        Recommendation(
            product_id=product.id,
            warehouse_id=warehouse.id,
            suggested_action="reorder",
            suggested_quantity=5,
            confidence_score=99,
            evidence={"note": "entered by a planner"},
            business_reasoning="Manual override from the supply chain team.",
            source="manual",
        )
    )
    db_session.commit()

    persist_reorder_recommendations(
        db_session,
        pd.DataFrame(
            [_forecast_row(company, warehouse, product, forecast_quantity=20)]
        ),
    )

    sources = sorted(r.source for r in db_session.query(Recommendation).all())
    assert sources == ["forecast_pipeline", "manual"]


def test_forecast_persistence_refuses_cross_tenant_references(
    db_session, company, other_company, make_warehouse, make_product
):
    foreign_product = make_product(other_company)
    foreign_warehouse = make_warehouse(other_company)

    created = persist_reorder_recommendations(
        db_session,
        pd.DataFrame(
            [
                {
                    "company_id": company.id,  # does not own either reference
                    "warehouse_id": foreign_warehouse.id,
                    "product_id": foreign_product.id,
                    "units_sold_in_window": 100,
                    "active_days": 10,
                    "avg_daily_sales": 3.3,
                    "forecast_quantity": 25,
                    "confidence_score": 33,
                }
            ]
        ),
    )

    assert created == 0
    assert db_session.query(Recommendation).count() == 0


# ---------------------------------------------------------------------------
# Whole chain
# ---------------------------------------------------------------------------
def test_sales_flow_all_the_way_through_to_a_visible_recommendation(
    db_session,
    authenticated_client,
    company,
    make_warehouse,
    make_product,
    make_stock,
    record_sale,
    lake,
):
    """Sales -> ETL -> Parquet -> forecast -> recommendation -> API response."""
    warehouse = make_warehouse(company)
    product = make_product(company, unit_cost=2, selling_price=10)
    make_stock(product, warehouse, quantity=0)

    # Steady demand: 4 units/day for 14 days.
    for days_ago in range(1, 15):
        record_sale(company, warehouse, product, quantity=4, days_ago=days_ago)

    run_nightly_etl(engine=db_session.get_bind(), data_lake_dir=lake)

    abc_df = run_abc_analysis(data_lake_dir=lake)
    forecast_df = run_demand_forecast(
        data_lake_dir=lake, lookback_days=30, horizon_days=7
    )
    persist_abc_classes(db_session, abc_df)
    persist_reorder_recommendations(db_session, forecast_df)
    db_session.commit()

    response = authenticated_client.get("/api/v1/recommendations/")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1

    rec = body["data"][0]
    assert rec["suggested_action"] == "reorder"
    assert rec["source"] == PIPELINE_SOURCE
    # 56 units over 30 days = 1.867/day -> 13 over a 7-day horizon, 0 on hand.
    assert rec["suggested_quantity"] == 13
    assert rec["evidence"]["active_days"] == 14

    # The product should also now carry an ABC class.
    product_response = authenticated_client.get(f"/api/v1/products/{product.id}")
    assert product_response.json()["abc_class"] == "A"
