import logging

from apscheduler.schedulers import SchedulerAlreadyRunningError
from apscheduler.schedulers.background import BackgroundScheduler

import app.models  # noqa: F401  — completes the ORM registry for standalone runs
from app.core.database import SessionLocal
from app.modules.analytics.abc_analysis import run_abc_analysis
from app.modules.analytics.accuracy import persist_forecast_runs, score_due_forecasts
from app.modules.analytics.forecast import run_demand_forecast
from app.modules.analytics.persistence import (
    persist_abc_classes,
    persist_reorder_recommendations,
)
from etl.pipeline import run_nightly_etl

logger = logging.getLogger(__name__)

# This runs in a separate thread alongside the FastAPI web server.
scheduler = BackgroundScheduler()


def run_nightly_analytics() -> dict:
    """Refresh the data lake, then derive and persist analytics from it.

    Chained rather than scheduled as three independent cron jobs, because the ABC
    classification and the demand forecast both read the Parquet file the ETL
    writes. As separate jobs an ETL overrun would silently leave them analysing
    yesterday's data.

    Previously this module defined its OWN log-only `run_abc_analysis` stub whose
    name shadowed the real implementation in app.modules.analytics. The scheduler
    registered the stub, so every night the logs reported "ABC Analysis complete!"
    while nothing was computed and nothing was stored.
    """
    logger.info("=== NIGHTLY ANALYTICS: START ===")
    summary = {
        "products_classified": 0,
        "recommendations_created": 0,
        "forecasts_recorded": 0,
        "forecasts_scored": 0,
    }

    run_nightly_etl()

    abc_df = run_abc_analysis()
    forecast_df = run_demand_forecast()

    db = SessionLocal()
    try:
        summary["products_classified"] = persist_abc_classes(db, abc_df)
        summary["recommendations_created"] = persist_reorder_recommendations(
            db, forecast_df
        )
        # Record tonight's predictions, then grade the ones whose window has
        # closed. Scoring runs before the new batch would be equally correct;
        # after is chosen so a forecast is never scored on the same night it
        # was made, which cannot happen but would be silent if it did.
        summary["forecasts_recorded"] = persist_forecast_runs(db, forecast_df)
        summary["forecasts_scored"] = score_due_forecasts(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Nightly analytics failed; database changes rolled back")
        raise
    finally:
        db.close()

    logger.info(f"=== NIGHTLY ANALYTICS: DONE {summary} ===")
    return summary


def archive_cold_data():
    """Data lifecycle policy: move records older than 24 months to cold storage.

    NOT IMPLEMENTED. Left unscheduled on purpose — a job that logs "Archival
    complete. Database performance optimal." without archiving anything is worse
    than no job at all, because it produces false assurance in the logs.
    """
    raise NotImplementedError("Data archival policy has not been implemented yet.")


def start_scheduler():
    logger.info("Starting background scheduler...")

    scheduler.add_job(
        run_nightly_analytics,
        "cron",
        hour=1,
        minute=0,
        id="nightly_analytics",
        replace_existing=True,
        # If the app restarts near the trigger time, run once rather than
        # stacking up every missed firing.
        coalesce=True,
        max_instances=1,
        misfire_grace_time=3600,
    )

    try:
        scheduler.start()
    except SchedulerAlreadyRunningError:
        logger.warning("Scheduler is already running.")
