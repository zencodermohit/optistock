"""Demand forecasting from the Parquet data lake.

Method: average daily velocity over a fixed trailing window, extrapolated across
the forecast horizon. Deliberately simple and fully explainable — every number
that drives a recommendation is recorded in its evidence payload.

A note on the velocity divisor
------------------------------
The original implementation averaged the per-day totals of days that HAD sales:

    daily_sales.groupby("product_id")["quantity"].mean()

That divides by the number of active days rather than the length of the window,
which massively overstates demand for intermittent items. A product selling 10
units on a single day of a 30-day window scored 10 units/day and was forecast to
need 70 units next week; true velocity is 10/30 = 0.33/day, or about 2 units.
Velocity is now total units divided by the FULL window length.
"""

import logging
from datetime import datetime, timedelta, timezone

import pandas as pd

from app.core.config import settings
from app.modules.analytics.data_lake import read_latest_fact_sales

logger = logging.getLogger(__name__)

RESULT_COLUMNS = [
    "company_id",
    "warehouse_id",
    "product_id",
    "units_sold_in_window",
    "active_days",
    "avg_daily_sales",
    "forecast_quantity",
    "confidence_score",
]


def _confidence(active_days: int, lookback_days: int) -> int:
    """How much demand history backs this forecast, as a 1-100 figure.

    This is a data-density heuristic, NOT a statistical confidence interval: a
    product that sold on 24 of 30 days is a far more reliable basis for a
    forecast than one that sold on a single day. Named accordingly in evidence
    so nobody mistakes it for a model probability.
    """
    ratio = active_days / lookback_days if lookback_days else 0
    return max(1, min(100, round(ratio * 100)))


def run_demand_forecast(
    data_lake_dir: str | None = None,
    lookback_days: int | None = None,
    horizon_days: int | None = None,
    as_of: datetime | None = None,
) -> pd.DataFrame:
    """Forecast demand per tenant, warehouse and product.

    Grouping includes warehouse_id because a reorder recommendation has to name
    the location being restocked — and Recommendation.warehouse_id is NOT NULL.
    """
    lookback_days = lookback_days or settings.FORECAST_LOOKBACK_DAYS
    horizon_days = horizon_days or settings.FORECAST_HORIZON_DAYS

    logger.info(f"[ANALYTICS] Forecasting demand over a {lookback_days}-day window...")

    df = read_latest_fact_sales(data_lake_dir)
    if df.empty:
        return pd.DataFrame(columns=RESULT_COLUMNS)

    df = df.copy()
    df["sale_date"] = pd.to_datetime(df["sale_date"], utc=True)

    cutoff = (as_of or datetime.now(timezone.utc)) - timedelta(days=lookback_days)
    window = df[df["sale_date"] >= cutoff]
    if window.empty:
        logger.info("[ANALYTICS] No sales inside the lookback window.")
        return pd.DataFrame(columns=RESULT_COLUMNS)

    window = window.assign(sale_day=window["sale_date"].dt.date)

    keys = ["company_id", "warehouse_id", "product_id"]
    grouped = window.groupby(keys, as_index=False).agg(
        units_sold_in_window=("quantity", "sum"),
        active_days=("sale_day", "nunique"),
    )

    # Divide by the whole window, not just the days that happened to have sales.
    grouped["avg_daily_sales"] = grouped["units_sold_in_window"] / lookback_days
    grouped["forecast_quantity"] = (
        (grouped["avg_daily_sales"] * horizon_days).round().astype(int)
    )
    grouped["confidence_score"] = grouped["active_days"].apply(
        lambda d: _confidence(int(d), lookback_days)
    )

    logger.info(
        f"[ANALYTICS] Forecast produced for {len(grouped)} product/warehouse pairs."
    )
    return grouped[RESULT_COLUMNS].reset_index(drop=True)
