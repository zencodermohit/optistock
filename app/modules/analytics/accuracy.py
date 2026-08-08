"""Recording forecasts, and scoring them against what actually happened.

Without this, a forecast is an assertion. The pipeline predicts demand, writes
a recommendation, and nothing ever checks whether the prediction was any good --
so "I built forecasting" is the most that can be claimed.

With it, every prediction is stored the night it is made, together with the date
its window closes. Once that date has passed the real demand over the same
window is filled in and the error recorded. Aggregating those errors turns the
claim into a number, and the number is allowed to be unflattering.

On the choice of error metric
-----------------------------
Textbook MAPE -- the mean of |actual - forecast| / actual -- is the wrong tool
for inventory demand, for a reason that shows up immediately in real data: it
divides by the actual, so a product that was forecast at 2 and sold 1 scores
100% error, and a product that sold 0 is undefined. A catalogue full of
slow-moving items therefore reports a terrible MAPE dominated by the rows that
matter least.

What is reported instead is a WEIGHTED absolute percentage error:

    sum(|actual - forecast|) / sum(actual)

which is defined whenever anything sold at all, and weights each product by how
much of the business it actually represents. MAE is reported alongside it in
plain units, because a percentage with no scale hides whether being 30% out
means three units or three thousand.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

import pandas as pd
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.analytics.models import ForecastRun
from app.modules.sales.models import Sale, SaleItem

logger = logging.getLogger(__name__)


def persist_forecast_runs(
    db: Session,
    forecast_df: pd.DataFrame,
    horizon_days: Optional[int] = None,
    predicted_at: Optional[datetime] = None,
) -> int:
    """Store tonight's predictions so they can be scored later. Returns rows written.

    Written for every forecast row, not only the ones that became a
    recommendation. Scoring only the predictions that led to an action would
    measure the pipeline's decisions rather than its forecasts, and quietly
    exclude every case where it predicted demand that never arrived.
    """
    if forecast_df.empty:
        return 0

    horizon_days = horizon_days or settings.FORECAST_HORIZON_DAYS
    predicted_at = predicted_at or datetime.now(timezone.utc)
    # The LAST day of the window, not the day after it. A 7-day horizon
    # starting today ends on day 6; scoring through day 7 would compare a
    # 7-day forecast against 8 days of sales and report the model as
    # under-predicting by a fixed amount forever.
    horizon_end = predicted_at.date() + timedelta(days=horizon_days - 1)

    rows = [
        {
            "company_id": row.company_id,
            "product_id": row.product_id,
            "warehouse_id": row.warehouse_id,
            "horizon_days": horizon_days,
            "forecast_quantity": int(row.forecast_quantity),
            "avg_daily_sales": float(row.avg_daily_sales),
            "confidence_score": int(row.confidence_score),
            "predicted_at": predicted_at,
            "horizon_end": horizon_end,
        }
        for row in forecast_df.itertuples(index=False)
    ]

    db.execute(ForecastRun.__table__.insert(), rows)
    db.flush()
    logger.info("[ANALYTICS] Recorded %d forecast runs for later scoring.", len(rows))
    return len(rows)


def score_due_forecasts(db: Session, as_of: Optional[date] = None) -> int:
    """Fill in what actually happened for every forecast whose window has closed.

    Returns the number of runs scored.

    Runs are grouped by their window before querying. Every prediction from one
    nightly batch shares a start and end date, so a handful of grouped queries
    answer what would otherwise be one query per forecast row -- the same N+1
    that would make this job slower every night the catalogue grows.
    """
    as_of = as_of or datetime.now(timezone.utc).date()

    due = (
        db.query(ForecastRun)
        .filter(
            ForecastRun.scored_at.is_(None),
            # Strictly less than: horizon_end is the last day of the window, so
            # on that day the window is still being filled and scoring would
            # grade a partial result as a miss.
            ForecastRun.horizon_end < as_of,
        )
        .all()
    )
    if not due:
        return 0

    by_window: Dict[tuple, list] = defaultdict(list)
    for run in due:
        by_window[(run.predicted_at.date(), run.horizon_end)].append(run)

    scored_at = datetime.now(timezone.utc)
    scored = 0

    for (start, end), runs in by_window.items():
        wanted = {(r.product_id, r.warehouse_id) for r in runs}

        actuals = {
            (row.product_id, row.warehouse_id): int(row.units or 0)
            for row in db.query(
                SaleItem.product_id,
                Sale.source_warehouse_id.label("warehouse_id"),
                func.sum(SaleItem.quantity).label("units"),
            )
            .join(Sale, SaleItem.sale_id == Sale.id)
            .filter(
                func.date(Sale.created_at) >= start,
                func.date(Sale.created_at) <= end,
            )
            .group_by(SaleItem.product_id, Sale.source_warehouse_id)
            .all()
            if (row.product_id, row.warehouse_id) in wanted
        }

        for run in runs:
            # Absent from the result means nothing sold, which is a real
            # outcome of zero -- not missing data to be skipped. Skipping it
            # would drop exactly the cases where the forecast over-predicted.
            actual = actuals.get((run.product_id, run.warehouse_id), 0)
            run.actual_quantity = actual
            run.absolute_error = abs(actual - run.forecast_quantity)
            run.scored_at = scored_at
            scored += 1

    db.flush()
    logger.info("[ANALYTICS] Scored %d forecasts against actual demand.", scored)
    return scored


def accuracy_summary(
    db: Session, company_id: UUID, lookback_days: int = 90
) -> Dict[str, Any]:
    """How good the forecasts have been, for one tenant.

    Returns None for the error figures rather than 0 when nothing has been
    scored yet. Zero error would read as a perfect forecast, which is the
    opposite of "we do not know yet".
    """
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    runs = (
        db.query(ForecastRun)
        .filter(
            ForecastRun.company_id == company_id,
            ForecastRun.scored_at.isnot(None),
            ForecastRun.scored_at >= since,
        )
        .all()
    )

    pending = (
        db.query(func.count(ForecastRun.id))
        .filter(
            ForecastRun.company_id == company_id,
            ForecastRun.scored_at.is_(None),
        )
        .scalar()
        or 0
    )

    if not runs:
        return {
            "scored": 0,
            "pending": pending,
            "weighted_ape": None,
            "mae": None,
            "within_20_pct": None,
            "total_forecast": 0,
            "total_actual": 0,
        }

    total_error = sum(r.absolute_error or 0 for r in runs)
    total_actual = sum(r.actual_quantity or 0 for r in runs)
    total_forecast = sum(r.forecast_quantity for r in runs)

    # Share of predictions that landed within a fifth of the truth. A single
    # headline average hides its own distribution: the same mean error is
    # produced by "mostly close, occasionally wild" and by "uniformly mediocre",
    # and those call for completely different fixes.
    close = sum(
        1
        for r in runs
        if r.actual_quantity
        and abs((r.actual_quantity or 0) - r.forecast_quantity)
        <= 0.2 * (r.actual_quantity or 1)
    )

    return {
        "scored": len(runs),
        "pending": pending,
        "weighted_ape": (total_error / total_actual * 100) if total_actual else None,
        "mae": total_error / len(runs),
        "within_20_pct": close / len(runs) * 100,
        "total_forecast": total_forecast,
        "total_actual": total_actual,
    }


def recent_scored_runs(db: Session, company_id: UUID, limit: int = 20):
    """The most recently scored predictions, worst error first.

    Ordered by how wrong they were rather than by date: the point of showing
    individual rows is to look at the misses, and a list sorted by recency
    buries them among the ones that went fine.
    """
    return (
        db.query(ForecastRun)
        .filter(
            ForecastRun.company_id == company_id,
            ForecastRun.scored_at.isnot(None),
        )
        .order_by(ForecastRun.absolute_error.desc())
        .limit(limit)
        .all()
    )
