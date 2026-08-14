"""Three years of trading history, generated to behave like a real business.

    python -m scripts.backfill_history            # both tenants
    python -m scripts.backfill_history --dry-run  # report, write nothing

The seeded dataset covered about twelve weeks. That is enough to compute a
velocity and not nearly enough for anything the word "trend" belongs in: no
season is visible in twelve weeks, year-on-year cannot be computed at all, and a
"1 year" filter on any screen is a filter over data that does not exist.

This writes sales BEFORE the existing window, so nothing already in the database
is touched. It is additive by construction.

WHAT MAKES IT PLAUSIBLE RATHER THAN RANDOM

Four signals are layered on top of each other, because real order volume is a
product of several rhythms rather than a single distribution:

    growth      the business compounds year on year, so 2023 is visibly
                smaller than 2025 and the early months look like a smaller
                company rather than the same company having a quiet week.
    season      Indian retail peaks hard into the festive quarter. October and
                November carry Diwali; March closes the financial year; the
                monsoon months are slow.
    week        a B2B distributor ships on working days. Saturday is a third of
                a Tuesday and Sunday is nearly nothing.
    category    electronics spike into the festive season, packaging follows
                whatever else is shipping, and safety equipment barely moves
                with the calendar at all.

STOCK IS DELIBERATELY NOT DEDUCTED. These rows are a record of trading that
already happened; current inventory is a fact about now. Replaying three years
of deductions against today's shelves would drive every line deep negative and
break the check constraint that exists to prevent exactly that.

daily_metrics is written alongside, because the projection is maintained by
consumers that will never see these events and the charts read from it.
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
from app.modules.analytics.projection_models import DailyMetric  # noqa: E402
from app.modules.products.models import Product  # noqa: E402
from app.modules.sales.models import Customer, Sale, SaleItem  # noqa: E402

YEARS = 3

#: Month multipliers. The festive quarter is the whole shape of Indian retail:
#: Navratri and Diwali land in Oct/Nov and pull a disproportionate share of the
#: year with them. March is the financial year end. June to August is monsoon
#: and slow.
SEASON = {
    1: 0.82,   # January — post-festive hangover
    2: 0.88,
    3: 1.18,   # March — financial year end
    4: 0.95,
    5: 0.92,
    6: 0.78,   # monsoon
    7: 0.76,
    8: 0.84,
    9: 1.05,   # build-up to the festive quarter
    10: 1.52,  # Navratri / Dussehra
    11: 1.64,  # Diwali — the peak of the year
    12: 1.12,  # year end
}

#: Monday is 0. A distributor ships on working days.
WEEKDAY = {0: 1.12, 1: 1.18, 2: 1.15, 3: 1.10, 4: 1.05, 5: 0.38, 6: 0.10}

#: How much each category cares about the festive season. 1.0 follows it
#: exactly; 0 ignores the calendar entirely.
SEASON_SENSITIVITY = {
    "Electronics": 1.35,
    "Furniture": 0.85,
    "Office Supplies": 0.60,
    "Networking": 0.70,
    "Safety & PPE": 0.25,
    "Packaging": 1.05,
}

#: Compound annual growth. The business is bigger every year, which is what
#: makes a year-on-year comparison worth drawing.
ANNUAL_GROWTH = 0.28

#: Trailing window used to measure how fast the business is trading TODAY.
#: The generated history is calibrated against this rather than a constant --
#: the two tenants differ by a factor of six, and one hardcoded rate would make
#: the small one's past bigger than its present.
CALIBRATION_DAYS = 90


def _multiplier(day: datetime, years_before_end: float) -> float:
    """How busy this particular day was, relative to a peak weekday."""
    growth = (1 + ANNUAL_GROWTH) ** -years_before_end
    return SEASON[day.month] * WEEKDAY[day.weekday()] * growth


def backfill(session: Session, company_id, dry_run: bool) -> dict:
    rng = random.Random(f"history-{company_id}")

    products = session.execute(
        select(Product).where(Product.company_id == company_id)
    ).scalars().all()
    customers = session.execute(
        select(Customer).where(Customer.company_id == company_id)
    ).scalars().all()
    warehouse_ids = [
        row[0]
        for row in session.execute(
            text("SELECT id FROM warehouses WHERE company_id = :c"),
            {"c": company_id},
        ).all()
    ]
    if not products or not customers or not warehouse_ids:
        return {"skipped": "missing products, customers or warehouses"}

    # Write up to the day before the earliest sale already recorded, so the two
    # datasets sit end to end with no overlap and no gap.
    earliest = session.execute(
        text("SELECT MIN(created_at) FROM sales WHERE company_id = :c"),
        {"c": company_id},
    ).scalar()
    end = (earliest or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = end - timedelta(days=365 * YEARS)

    # Calibrate against how this tenant actually trades now. The history has to
    # arrive at roughly today's rate divided by one year of growth, or the join
    # between generated and real data is a visible cliff -- and if the constant
    # is too high, the past ends up larger than the present, which is the
    # opposite of the growth story the data is meant to show.
    recent = session.execute(
        text(
            """
            SELECT COUNT(*)::float / :days
            FROM sales
            WHERE company_id = :c AND created_at >= :since
            """
        ),
        {
            "c": company_id,
            "days": CALIBRATION_DAYS,
            "since": datetime.now(timezone.utc) - timedelta(days=CALIBRATION_DAYS),
        },
    ).scalar() or 0.0
    if recent <= 0:
        return {"skipped": "no recent sales to calibrate against"}

    # The generator's own average multiplier, so the produced mean lands on the
    # target instead of being scaled by whatever season and weekday average to.
    mean_multiplier = (
        sum(SEASON.values()) / len(SEASON) * sum(WEEKDAY.values()) / len(WEEKDAY)
    )
    peak_orders = (recent / (1 + ANNUAL_GROWTH)) / mean_multiplier

    # Basket size is measured too. Order RATE alone is not enough: generating
    # the right number of orders with baskets three times too big produces a
    # past richer than the present, which is the same inversion in a different
    # column. Both halves have to come from the data.
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

    # Calibrate on the OUTCOME, not the parts. Rounding the two component
    # averages independently compounded: 2.5 lines and 2.5 units each rounded
    # down produced an order worth 44% of a real one. What has to match is
    # revenue per order, so the components are scaled until it does.
    measured = session.execute(
        text(
            "SELECT COALESCE(SUM(total_amount),0)/NULLIF(COUNT(*),0) "
            "FROM sales WHERE company_id = :c"
        ),
        {"c": company_id},
    ).scalar() or 0.0
    mean_price = sum(float(p.selling_price or 0) for p in products) / len(products)
    expected = mean_lines * mean_units * mean_price
    correction = (float(measured) / expected) if expected > 0 else 1.0
    mean_units *= correction

    # Guard on the SPAN, not on "is there anything before the earliest row".
    #
    # The first version asked whether sales existed before the earliest sale,
    # which is zero by definition and therefore never true. Running the script
    # twice prepended a second three years in front of the first, and a third
    # run added another -- leaving seven years with a visible seam at each join
    # and a growth curve that went backwards across them.
    span = session.execute(
        text(
            "SELECT COALESCE(MAX(created_at)::date - MIN(created_at)::date, 0) "
            "FROM sales WHERE company_id = :c"
        ),
        {"c": company_id},
    ).scalar() or 0
    if span >= YEARS * 365:
        return {"skipped": f"history already spans {span:,} days"}

    by_category = {}
    for product in products:
        by_category.setdefault(product.category or "Other", []).append(product)

    sales_rows, item_rows, metrics = [], [], {}
    day = start
    while day < end - timedelta(days=1):
        years_before_end = (end - day).days / 365
        base = peak_orders * _multiplier(day, years_before_end)
        # Poisson-ish jitter, so no two days are identical and the series has
        # the texture of a real one rather than a smooth curve.
        orders = max(0, int(rng.gauss(base, base * 0.22)))

        day_revenue = day_units = 0

        for _ in range(orders):
            # Categories are weighted by how much they care about the season,
            # so the festive peak is visibly ELECTRONICS rather than everything
            # rising together.
            weights = [
                SEASON_SENSITIVITY.get(cat, 0.8) ** 2 * (SEASON[day.month] - 0.7)
                + 0.4
                for cat in by_category
            ]
            category = rng.choices(list(by_category), weights=weights, k=1)[0]
            pool = by_category[category]

            sale_id = uuid.uuid4()
            when = day.replace(
                hour=rng.randint(8, 19), minute=rng.randint(0, 59)
            )
            total = 0.0
            lines = []
            line_count = max(1, round(rng.gauss(mean_lines, 0.7)))
            for product in rng.sample(pool, k=min(len(pool), line_count)):
                quantity = max(1, int(rng.gauss(mean_units, mean_units * 0.45)))
                price = float(product.selling_price or 0)
                total += quantity * price
                day_units += quantity
                lines.append(
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
            item_rows.extend(lines)
            day_revenue += total

        metrics[day.date()] = {
            "company_id": company_id,
            "metric_date": day.date(),
            "revenue": round(day_revenue, 2),
            "orders": orders,
            "units_sold": day_units,
            "stock_movements": day_units,
            "units_received": 0,
        }
        day += timedelta(days=1)

    summary = {
        "rate_now": round(recent, 1),
        "rate_generated": round(peak_orders * mean_multiplier, 1),
        "basket": f"{mean_lines:.1f} lines x {mean_units:.1f} units",
        "order_value_now": round(float(measured)),
        "from": start.date().isoformat(),
        "to": (end - timedelta(days=1)).date().isoformat(),
        "sales": len(sales_rows),
        "lines": len(item_rows),
        "days": len(metrics),
        "revenue": round(sum(m["revenue"] for m in metrics.values()), 2),
    }
    if dry_run:
        return summary

    # Chunked, because a single 200,000-row INSERT is a statement no driver
    # enjoys and a transaction nobody can interrupt.
    def chunked(rows, table, size=5000):
        for i in range(0, len(rows), size):
            session.execute(insert(table), rows[i : i + size])

    chunked(sales_rows, Sale)
    chunked(item_rows, SaleItem)
    chunked(list(metrics.values()), DailyMetric)
    session.commit()
    return summary


def align_product_ages(session: Session) -> int:
    """Backdate each product to just before its first sale.

    The seed stamps every product with the moment the database was built, which
    was harmless when the sales history was twelve weeks old and is nonsense now
    that it runs three years: a product cannot have been sold in 2022 and
    created last month. It also made "new products" count the entire catalogue,
    which is the same as counting nothing.

    A few days before the first sale rather than exactly on it, because stock
    has to be received before it can be sold. Products that have never sold keep
    their original date and stay genuinely new.
    """
    result = session.execute(
        text(
            """
            UPDATE products p
            SET created_at = first_sale.at - INTERVAL '5 days'
            FROM (
                SELECT si.product_id, MIN(s.created_at) AS at
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                GROUP BY si.product_id
            ) first_sale
            WHERE p.id = first_sale.product_id
              AND p.created_at > first_sale.at
            """
        )
    )
    session.commit()
    return result.rowcount


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = create_engine(settings.DATABASE_URL)
    with Session(engine) as session:
        companies = session.execute(text("SELECT id, name FROM companies")).all()
        for company_id, name in companies:
            result = backfill(session, company_id, args.dry_run)
            print(f"\n{name}")
            for key, value in result.items():
                print(f"  {key:10} {value:,}" if isinstance(value, int) else f"  {key:10} {value}")

        if not args.dry_run:
            aligned = align_product_ages(session)
            print(f"\nBackdated {aligned:,} products to precede their first sale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
