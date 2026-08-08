"""Recompute the daily metrics projection from the source tables.

    python -m app.workers.rebuild_projections            # everything
    python -m app.workers.rebuild_projections --days 90  # recent history only

Run it after seeding, after changing how a metric is calculated, or any time the
incremental path is suspected of having drifted. Being able to say "throw the
read model away and rebuild it" is the property that makes projections safe to
iterate on -- the source tables are the truth, and this table is an opinion
about them that can always be re-formed.
"""

import argparse
import logging
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  — completes the ORM registry for standalone runs
from app.core.database import SessionLocal
from app.modules.analytics.projections import rebuild_daily_metrics

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Rebuild the daily metrics projection."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only rebuild this many days back. Omit to rebuild all history.",
    )
    args = parser.parse_args()

    since = None
    if args.days:
        since = datetime.now(timezone.utc).date() - timedelta(days=args.days - 1)

    db = SessionLocal()
    try:
        written = rebuild_daily_metrics(db, since=since)
        db.commit()
        print(f"Rebuilt {written} daily metric rows.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
