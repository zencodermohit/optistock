"""Generate and score historical forecasts, so accuracy has a track record.

    python -m app.workers.backfill_forecasts --weeks 8

The nightly job records one batch of predictions per night and scores each batch
once its horizon has elapsed. That is correct, and it means a freshly seeded
system reports no accuracy at all until it has been running for longer than a
forecast horizon.

This walks the same forecast backwards through history instead. For each past
date it re-runs `run_demand_forecast(as_of=...)`, which reads only the sales the
data lake shows up to that point, stores the result as if it had been made that
night, and then scores it against what actually sold afterwards. The numbers it
produces are therefore honest out-of-sample results, not a model grading itself
on data it already saw -- the only thing being simulated is the passage of time.
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  — completes the ORM registry for standalone runs
from app.core.config import settings
from app.core.database import SessionLocal
from app.modules.analytics.accuracy import persist_forecast_runs, score_due_forecasts
from app.modules.analytics.forecast import run_demand_forecast
from app.modules.analytics.models import ForecastRun

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Backfill and score historical forecast runs."
    )
    parser.add_argument(
        "--weeks", type=int, default=8, help="How many past weeks to forecast."
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing forecast runs first, instead of adding to them.",
    )
    args = parser.parse_args()

    horizon = settings.FORECAST_HORIZON_DAYS
    now = datetime.now(timezone.utc)

    db = SessionLocal()
    try:
        if args.replace:
            deleted = db.query(ForecastRun).delete()
            logger.info("Cleared %d existing forecast runs.", deleted)

        recorded = 0
        # Oldest first, and stopping one horizon short of today: a forecast made
        # this week has not finished happening yet, so there is nothing to score
        # it against.
        for week in range(args.weeks, 0, -1):
            as_of = now - timedelta(days=week * 7)
            if as_of + timedelta(days=horizon) > now:
                continue

            forecast = run_demand_forecast(as_of=as_of)
            if forecast.empty:
                logger.info("No sales in the window ending %s; skipping.", as_of.date())
                continue

            recorded += persist_forecast_runs(
                db, forecast, horizon_days=horizon, predicted_at=as_of
            )

        scored = score_due_forecasts(db)
        db.commit()
        print(f"Recorded {recorded} forecast runs, scored {scored}.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
