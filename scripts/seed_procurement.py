"""Give the purchasing side a history.

The purchase order table held three rows, all drafts. Every figure on the
procurement screen -- open orders, delayed deliveries, supplier lead times,
received value -- was therefore zero or three, and a page that can only ever
report zero cannot be judged, demonstrated or debugged.

Two things here are deliberate.

Lead time is not stored on the supplier. There is no column for it and this does
not add one. Instead each supplier is given a characteristic lead time that
shows up in the DATES of its orders, and the read model measures it back out of
that history. That is the honest loop: the generator states a fact by making it
happen, and the application discovers it by looking. A lead_time_days column
would let the page report a number nobody had ever observed.

Delays are correlated with reliability_score, which until now was a column
nothing consulted. A supplier at 0.72 misses its dates more often than one at
0.98, so "which suppliers are hurting us" becomes a question the data can
actually answer rather than a chart of random noise.

    python scripts/seed_procurement.py --dry-run
    python scripts/seed_procurement.py
"""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: F401,E402
from app.core.database import SessionLocal  # noqa: E402

#: How far back the ordering history runs. Long enough that lead times have
#: something to average and that "delivered last quarter" is a real category.
MONTHS = 18

#: Two hundred SKUs across five warehouses, reordered on a monthly-ish cycle,
#: is not seven purchase orders a month. Seven was the figure that left only
#: eight orders ever in flight -- arithmetically consistent and nothing like a
#: business turning over fifty crore a year.
ORDERS_PER_MONTH = 45

#: The lifecycle. A purchase order is raised, sent, and either arrives or is
#: cancelled -- these are the four states the service already writes, and
#: inventing a fifth here would mean the seeded data could reach a state the
#: application cannot produce.
DRAFT, SUBMITTED, DELIVERED, CANCELLED = "draft", "submitted", "delivered", "cancelled"

#: Share of orders that never arrive. Low, because a business that cancels one
#: order in five has a bigger problem than its dashboard.
CANCEL_RATE = 0.06

#: Share of orders, of any age, that were raised and never sent. Stale drafts
#: are a real procurement failure -- somebody built a basket and forgot it --
#: and they are the reason the approvals queue on that page has anything in it.
STALE_DRAFT_RATE = 0.012

#: Lead times a supplier can have, in days. Drawn once per supplier and held,
#: because the whole point is that a supplier HAS a characteristic lead time.
LEAD_TIMES = [3, 5, 7, 10, 14, 21, 28]

SEED = 20260814


def _lead_time(rng: random.Random) -> int:
    # Weighted towards the middle: most trade is on a one-to-two week cycle,
    # with a few fast local suppliers and a few slow imports.
    return rng.choices(LEAD_TIMES, weights=[8, 14, 18, 20, 16, 10, 6])[0]


def seed(session: Session, company_id, company_name: str, dry_run: bool) -> dict:
    rng = random.Random(f"{SEED}-{company_id}")
    now = datetime.now(timezone.utc)

    # The guard measures the outcome. Anything beyond the handful of drafts the
    # seed already made means this has run.
    existing = session.execute(
        text("SELECT COUNT(*) FROM purchase_orders WHERE company_id = :cid"),
        {"cid": company_id},
    ).scalar()
    if existing > 20:
        return {"skipped": f"{existing} purchase orders already exist"}

    suppliers = session.execute(
        text(
            "SELECT id, name, COALESCE(reliability_score, 0.9) AS reliability "
            "FROM suppliers WHERE company_id = :cid AND is_active"
        ),
        {"cid": company_id},
    ).all()
    warehouses = [
        r[0]
        for r in session.execute(
            text(
                "SELECT id FROM warehouses WHERE company_id = :cid AND is_active"
            ),
            {"cid": company_id},
        ).all()
    ]
    # Products worth reordering, with the rate that says how many to order.
    products = session.execute(
        text(
            """
            SELECT p.id, p.unit_cost,
                   COALESCE(SUM(si.quantity), 0) / 365.0 AS daily_rate
            FROM products p
            LEFT JOIN sale_items si ON si.product_id = p.id
            LEFT JOIN sales s
                   ON s.id = si.sale_id
                  AND s.created_at >= NOW() - INTERVAL '365 days'
            WHERE p.company_id = :cid AND p.status = 'active'
            GROUP BY p.id, p.unit_cost
            HAVING COALESCE(SUM(si.quantity), 0) > 0
            """
        ),
        {"cid": company_id},
    ).all()

    if not suppliers or not warehouses or not products:
        return {"skipped": "no suppliers, warehouses or selling products"}

    # Each supplier's characteristic lead time, fixed for the whole history.
    lead_times = {s.id: _lead_time(rng) for s in suppliers}

    orders, items = [], []
    counts = {DRAFT: 0, SUBMITTED: 0, DELIVERED: 0, CANCELLED: 0}
    delayed = 0

    for month in range(MONTHS):
        # Ordering volume grows with the business, matching the sales history.
        scale = 1.0 + 0.02 * (MONTHS - month)
        for _ in range(int(rng.gauss(ORDERS_PER_MONTH * scale, 1.6))):
            days_ago = month * 30 + rng.randint(0, 29)
            raised = now - timedelta(days=days_ago, hours=rng.randint(8, 18))

            supplier = rng.choice(suppliers)
            lead = lead_times[supplier.id]
            expected = (raised + timedelta(days=lead)).date()

            # Reliability decides whether this one slips, and by how much. A
            # supplier at 0.98 slips rarely; one at 0.7 slips often.
            #
            # The slip does NOT move the expected date. Adding it there made the
            # promise follow the delivery around, so a supplier that missed
            # every deadline was never late -- it had simply promised later. The
            # promise is what was agreed; the slip is the failure to meet it,
            # and the gap between the two is the only place lateness can live.
            reliability = float(supplier.reliability)
            slip = rng.randint(2, 12) if rng.random() > reliability else 0

            # State follows from age, measured against when the order was
            # ACTUALLY going to arrive rather than when it was promised.
            #
            # Comparing against the promise marked slipped orders delivered on
            # their original date, which meant a supplier could miss every
            # deadline and never appear late. An order is late precisely
            # because its supplier slipped, so the slip has to be what keeps it
            # in transit.
            arrival = lead + slip

            if rng.random() < CANCEL_RATE:
                status = CANCELLED
            elif rng.random() < STALE_DRAFT_RATE:
                status = DRAFT  # raised and never sent
            elif days_ago > arrival:
                status = DELIVERED
            elif days_ago > 2:
                status = SUBMITTED
            else:
                status = DRAFT

            if status == SUBMITTED and expected < now.date():
                delayed += 1

            lines = []
            total = 0.0
            for product in rng.sample(products, k=rng.randint(1, 4)):
                # Roughly a month of cover per line, floored so a slow mover
                # still gets a sensible minimum order rather than one unit.
                rate = float(product.daily_rate)
                quantity = max(int(rate * rng.randint(21, 45)), rng.randint(10, 40))
                price = float(product.unit_cost)
                lines.append((product.id, quantity, price))
                total += quantity * price

            orders.append(
                {
                    "company_id": company_id,
                    "supplier_id": supplier.id,
                    "warehouse_id": rng.choice(warehouses),
                    "status": status,
                    "expected": expected,
                    "total": round(total, 2),
                    "created_at": raised,
                }
            )
            items.append(lines)
            counts[status] += 1

    if dry_run:
        return {
            "company": company_name,
            "orders": len(orders),
            "counts": counts,
            "delayed": delayed,
            "value": round(sum(o["total"] for o in orders)),
            "lead_times": {s.name: lead_times[s.id] for s in suppliers},
        }

    for order, lines in zip(orders, items):
        po_id = session.execute(
            text(
                """
                INSERT INTO purchase_orders (id, company_id, supplier_id,
                    destination_warehouse_id, status, expected_delivery_date,
                    total_amount, created_at)
                VALUES (gen_random_uuid(), :company_id, :supplier_id, :warehouse_id,
                        :status, :expected, :total, :created_at)
                RETURNING id
                """
            ),
            order,
        ).scalar()
        for product_id, quantity, price in lines:
            session.execute(
                text(
                    """
                    INSERT INTO po_items (id, po_id, product_id, quantity, unit_price)
                    VALUES (gen_random_uuid(), :po, :product, :qty, :price)
                    """
                ),
                {"po": po_id, "product": product_id, "qty": quantity, "price": price},
            )

    session.commit()
    return {
        "company": company_name,
        "orders": len(orders),
        "counts": counts,
        "delayed": delayed,
        "value": round(sum(o["total"] for o in orders)),
        "lead_times": {s.name: lead_times[s.id] for s in suppliers},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        for company_id, name in session.execute(
            text("SELECT id, name FROM companies")
        ).all():
            result = seed(session, company_id, name, args.dry_run)
            print(f"\n=== {name} ===")
            if "skipped" in result:
                print(f"  skipped: {result['skipped']}")
                continue
            print(f"  {result['orders']} orders worth {result['value']:,}")
            print(f"  {result['counts']}")
            print(f"  {result['delayed']} past their expected date and not received")
            print("  supplier lead times:")
            for supplier, days in sorted(
                result["lead_times"].items(), key=lambda kv: kv[1]
            ):
                print(f"    {days:>3}d  {supplier}")
        if args.dry_run:
            print("\nDry run — nothing was written.")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
