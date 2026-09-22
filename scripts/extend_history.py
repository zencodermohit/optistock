"""Bring the trading history up to today.

THE PROBLEM THIS SOLVES. A seeded history is generated once, against the date
it was generated on, and then the calendar keeps moving. Weeks later every
"last 30 days" panel is empty -- not broken, just looking at a window that ends
after the data does. The dashboards are correct and the database is stale, and
the two are hard to tell apart from the front end.

WHAT IT DOES. Fills forward from the most recent real sale to today, using the
same seasonality, weekday shape, category weighting and growth curve as
``backfill_history.py`` -- imported from it rather than restated, so the joint
between old and new days cannot drift as one of them is edited.

WHAT IT DOES NOT DO. It does not touch stock, for the same reason the backfill
does not: these are records of trading that already happened, while inventory
is a fact about now. Replaying deductions against today's shelves would drive
lines negative and hit the check constraint that exists to stop exactly that.

CALIBRATION ANCHORS ON THE LAST SALE, NOT ON TODAY. The obvious thing is to
measure the trailing ninety days from now, which is wrong here by construction:
the gap being filled is part of that window and contains nothing, so the
measured rate comes out low in proportion to how stale the data is, and the new
days are generated quieter than the old ones. The rate is measured over the
ninety days ending at the last real sale, where there is data to measure.

    python scripts/extend_history.py              # report only
    python scripts/extend_history.py --apply      # write

Dry by default. A script that writes to a database on an unqualified run is one
mistyped command away from being the reason you need the backup.
"""

import argparse
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, insert, select, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: F401,E402  -- registry
from app.core.config import settings  # noqa: E402
from app.modules.analytics.projections import rebuild_daily_metrics  # noqa: E402
from app.modules.products.models import Product  # noqa: E402
from app.modules.sales.models import Customer, Sale, SaleItem  # noqa: E402
from scripts.backfill_history import (  # noqa: E402
    ANNUAL_GROWTH,
    CALIBRATION_DAYS,
    SEASON,
    SEASON_SENSITIVITY,
    WEEKDAY,
)


def _multiplier(day: datetime, years_after_anchor: float) -> float:
    """How busy this day is, relative to a peak weekday at the anchor.

    The sign is the only thing that differs from the backfill's version. That
    one walks backwards from a known point and shrinks the business as it goes;
    this one walks forwards and grows it, so the gap continues the same curve
    rather than flattening out across it.
    """
    growth = (1 + ANNUAL_GROWTH) ** years_after_anchor
    return SEASON[day.month] * WEEKDAY[day.weekday()] * growth


def extend(session: Session, company_id, apply: bool) -> dict:
    rng = random.Random(f"extend-{company_id}")

    products = (
        session.execute(select(Product).where(Product.company_id == company_id))
        .scalars()
        .all()
    )
    customers = (
        session.execute(select(Customer).where(Customer.company_id == company_id))
        .scalars()
        .all()
    )
    warehouse_ids = [
        row[0]
        for row in session.execute(
            text("SELECT id FROM warehouses WHERE company_id = :c"),
            {"c": company_id},
        ).all()
    ]
    if not products or not customers or not warehouse_ids:
        return {"skipped": "missing products, customers or warehouses"}

    anchor = session.execute(
        text("SELECT MAX(created_at) FROM sales WHERE company_id = :c"),
        {"c": company_id},
    ).scalar()
    if anchor is None:
        return {"skipped": "no sales to extend from"}

    anchor = anchor.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    start = (anchor + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    if start.date() > now.date():
        return {"skipped": "history is already current"}

    # Measured over the window ending at the anchor. See the module docstring:
    # measuring from today would sample the hole this script exists to fill.
    recent = (
        session.execute(
            text(
                """
                SELECT COUNT(*)::float / :days
                FROM sales
                WHERE company_id = :c
                  AND created_at >= :since
                  AND created_at <= :anchor
                """
            ),
            {
                "c": company_id,
                "days": CALIBRATION_DAYS,
                "since": anchor - timedelta(days=CALIBRATION_DAYS),
                "anchor": anchor,
            },
        ).scalar()
        or 0.0
    )
    if recent <= 0:
        return {"skipped": "no sales near the anchor to calibrate against"}

    mean_multiplier = (
        sum(SEASON.values()) / len(SEASON) * sum(WEEKDAY.values()) / len(WEEKDAY)
    )
    peak_orders = recent / mean_multiplier

    basket = session.execute(
        text(
            """
            SELECT AVG(lines)::float, AVG(units)::float
            FROM (
                SELECT si.sale_id,
                       COUNT(*) AS lines,
                       AVG(si.quantity)::float AS units
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE s.company_id = :c
                GROUP BY si.sale_id
            ) per_sale
            """
        ),
        {"c": company_id},
    ).one()
    mean_lines = max(basket[0] or 2.0, 1.0)
    mean_units = max(basket[1] or 4.0, 1.0)

    # Calibrate on revenue per order, not on the two components separately.
    # Rounding each independently compounds, and the result is an order worth
    # noticeably less than a real one -- which shows up as a revenue cliff on
    # the exact day the generated data starts.
    measured = (
        session.execute(
            text(
                "SELECT COALESCE(SUM(total_amount),0)/NULLIF(COUNT(*),0) "
                "FROM sales WHERE company_id = :c"
            ),
            {"c": company_id},
        ).scalar()
        or 0.0
    )
    mean_price = sum(float(p.selling_price or 0) for p in products) / len(products)
    expected = mean_lines * mean_units * mean_price
    mean_units *= (float(measured) / expected) if expected > 0 else 1.0

    by_category = {}
    for product in products:
        by_category.setdefault(product.category or "Other", []).append(product)

    sales_rows, item_rows = [], []
    days = 0
    revenue_total = 0.0

    day = start
    while day.date() <= now.date():
        years_after = (day - anchor).days / 365
        base = peak_orders * _multiplier(day, years_after)
        orders = max(0, int(rng.gauss(base, base * 0.22)))

        # Today is only partly over, so generating a full day's trading would
        # put a spike on the right edge of every chart.
        if day.date() == now.date():
            orders = int(orders * min(1.0, now.hour / 20))

        for _ in range(orders):
            weights = [
                SEASON_SENSITIVITY.get(cat, 0.8) ** 2 * (SEASON[day.month] - 0.7) + 0.4
                for cat in by_category
            ]
            category = rng.choices(list(by_category), weights=weights, k=1)[0]
            pool = by_category[category]

            sale_id = uuid.uuid4()
            when = day.replace(hour=rng.randint(8, 19), minute=rng.randint(0, 59))
            total = 0.0
            line_count = max(1, round(rng.gauss(mean_lines, 0.7)))
            for product in rng.sample(pool, k=min(len(pool), line_count)):
                quantity = max(1, int(rng.gauss(mean_units, mean_units * 0.45)))
                price = float(product.selling_price or 0)
                total += quantity * price
                item_rows.append(
                    {
                        "id": uuid.uuid4(),
                        "sale_id": sale_id,
                        "product_id": product.id,
                        "quantity": quantity,
                        "unit_price": price,
                    }
                )

            sales_rows.append(
                {
                    "id": sale_id,
                    "company_id": company_id,
                    "customer_id": rng.choice(customers).id,
                    "source_warehouse_id": rng.choice(warehouse_ids),
                    "status": "completed",
                    "total_amount": round(total, 2),
                    "created_at": when,
                }
            )
            revenue_total += total

        days += 1
        day += timedelta(days=1)

    summary = {
        "from": start.date().isoformat(),
        "to": now.date().isoformat(),
        "days": days,
        "rate_at_anchor": round(recent, 1),
        "basket": f"{mean_lines:.1f} lines x {mean_units:.1f} units",
        "sales": len(sales_rows),
        "lines": len(item_rows),
        "revenue": round(revenue_total, 2),
    }
    if not apply:
        summary["mode"] = "dry run, nothing written"
        return summary

    def chunked(rows, table, size=5000):
        for i in range(0, len(rows), size):
            session.execute(insert(table), rows[i : i + size])

    chunked(sales_rows, Sale)
    chunked(item_rows, SaleItem)
    session.commit()

    # Derived from the rows just written rather than accumulated alongside
    # them. The projection has a (company_id, metric_date) primary key and the
    # gap already holds empty rows written by the consumers, so inserting
    # would collide; rebuilding deletes the range and recomputes it.
    written = rebuild_daily_metrics(session, company_id=company_id, since=start.date())
    session.commit()
    summary["metric_days_rebuilt"] = written
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write; without it, report only"
    )
    args = parser.parse_args()

    engine = create_engine(settings.DATABASE_URL)
    with Session(engine) as session:
        for company_id, name in session.execute(
            text("SELECT id, name FROM companies")
        ).all():
            result = extend(session, company_id, args.apply)
            print(f"\n{name}")
            for key, value in result.items():
                print(
                    f"  {key:20} {value:,}"
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                    else f"  {key:20} {value}"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
