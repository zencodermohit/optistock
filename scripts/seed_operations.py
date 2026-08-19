"""Give the operational screens something to be about.

Transfers, Stock counts and Alerts were all empty, and none of them was broken.
seed_db.py builds a catalogue and a year of selling; it does not simulate the
day-to-day of running the buildings, so three screens correctly reported that
nothing had happened. A screen that can only ever say "nothing here" cannot be
demonstrated, judged, or debugged.

WHY ALERTS HAVE TO BE WRITTEN DIRECTLY. Alerts are normally raised by the event
consumers reacting to stock movements. The seeded year predates the event system
-- it writes sales rows, not events -- so nothing ever replayed it and no alert
was ever raised. Rather than fabricate events, this writes the alerts the
consumers WOULD have raised, using the same alert_type, severity and subject
that app/modules/alerts uses, and derives each one from a real stock line that
is genuinely below its reorder point. Every alert on the screen points at a
product you can click through to and verify. Nothing is invented.

The same rule governs the rest. Transfers move real products between real
warehouses in quantities the source actually holds. Stock counts record real
expected quantities and put plausible, small discrepancies against them, because
a variance report where everything is out by 40% is not a demo, it is noise.

    python scripts/seed_operations.py --dry-run
    python scripts/seed_operations.py
    python scripts/seed_operations.py --reset    # clear and regenerate

Idempotent by refusal, like seed_procurement: it will not stack a second set on
top of an existing one without --reset.
"""

import argparse
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

import app.models  # noqa: F401,E402  — completes the ORM registry
from app.core.database import SessionLocal  # noqa: E402

SEED = 20260819
TRANSFERS_PER_COMPANY = 14
COUNTS_PER_COMPANY = 6

#: Reasons a physical count disagrees with the system. Real ones, in the
#: proportions a real warehouse sees them: miscounts dominate, theft is rare.
DISCREPANCY_REASONS = [
    ("Miscount at previous cycle count", 40),
    ("Damaged in handling, not written off", 20),
    ("Received but not booked in", 15),
    ("Picked against wrong line", 15),
    ("Unexplained shrinkage", 10),
]


def _weighted(pairs, rng):
    total = sum(w for _, w in pairs)
    r = rng.uniform(0, total)
    upto = 0
    for value, weight in pairs:
        upto += weight
        if r <= upto:
            return value
    return pairs[-1][0]


def seed(reset: bool = False, dry_run: bool = False) -> None:
    rng = random.Random(SEED)
    db = SessionLocal()
    now = datetime.now(timezone.utc)

    try:
        existing = db.execute(text("SELECT count(*) FROM transfers")).scalar() or 0
        if existing and not reset:
            print(
                f"\n  {existing} transfers already present."
                " Use --reset to clear and regenerate.\n"
            )
            return

        if reset and not dry_run:
            # Children first: these tables have no ON DELETE CASCADE, so the
            # order is load-bearing rather than stylistic.
            for table in (
                "transfer_items",
                "transfers",
                "reconciliation_items",
                "reconciliations",
                "alerts",
            ):
                db.execute(text(f"DELETE FROM {table}"))
            print("  Cleared existing transfers, stock counts and alerts.")

        companies = db.execute(
            text("SELECT id, name FROM companies ORDER BY name")
        ).fetchall()

        for company in companies:
            warehouses = db.execute(
                text(
                    "SELECT id, name FROM warehouses WHERE company_id = :c ORDER BY name"
                ),
                {"c": company.id},
            ).fetchall()

            if len(warehouses) < 2:
                print(
                    f"  {company.name}: only {len(warehouses)} warehouse, "
                    "skipping transfers (a transfer needs somewhere to go)"
                )
            counts = {"transfers": 0, "stock_counts": 0, "alerts": 0}

            # ---------------------------------------------------- transfers --
            #
            # Only ever moves stock the source warehouse genuinely holds, so a
            # transfer on screen can be traced to a line that could really have
            # supplied it.
            if len(warehouses) >= 2:
                stock = db.execute(
                    text(
                        """
                        SELECT i.warehouse_id, i.product_id, i.quantity
                        FROM inventory i
                        JOIN products p ON p.id = i.product_id
                        WHERE p.company_id = :c AND i.quantity > 20
                        ORDER BY i.quantity DESC
                        LIMIT 400
                        """
                    ),
                    {"c": company.id},
                ).fetchall()

                by_warehouse = {}
                for row in stock:
                    by_warehouse.setdefault(row.warehouse_id, []).append(row)

                for n in range(TRANSFERS_PER_COMPANY):
                    sources = [w for w in warehouses if by_warehouse.get(w.id)]
                    if not sources:
                        break
                    source = rng.choice(sources)
                    destination = rng.choice(
                        [w for w in warehouses if w.id != source.id]
                    )

                    # Spread across the last six weeks, and give the mix the
                    # shape an operations screen actually has: mostly finished,
                    # a few moving, a couple still to be picked.
                    age_days = rng.randint(0, 42)
                    created = now - timedelta(days=age_days, hours=rng.randint(0, 23))

                    if age_days > 10:
                        status, shipped, received = (
                            "completed",
                            created + timedelta(days=1),
                            created + timedelta(days=rng.randint(2, 5)),
                        )
                    elif age_days > 3:
                        status, shipped, received = (
                            "in_transit",
                            created + timedelta(days=1),
                            None,
                        )
                    else:
                        status, shipped, received = "pending", None, None

                    transfer_id = str(uuid.uuid4())
                    if not dry_run:
                        db.execute(
                            text(
                                """
                                INSERT INTO transfers
                                    (id, company_id, source_warehouse_id,
                                     destination_warehouse_id, status,
                                     shipped_at, received_at, created_at)
                                VALUES (:id, :c, :src, :dst, :st, :sh, :rc, :cr)
                                """
                            ),
                            {
                                "id": transfer_id,
                                "c": company.id,
                                "src": source.id,
                                "dst": destination.id,
                                "st": status,
                                "sh": shipped,
                                "rc": received,
                                "cr": created,
                            },
                        )
                        for line in rng.sample(
                            by_warehouse[source.id],
                            min(rng.randint(1, 4), len(by_warehouse[source.id])),
                        ):
                            db.execute(
                                text(
                                    """
                                    INSERT INTO transfer_items
                                        (id, transfer_id, product_id, quantity)
                                    VALUES (:id, :t, :p, :q)
                                    """
                                ),
                                {
                                    "id": str(uuid.uuid4()),
                                    "t": transfer_id,
                                    "p": line.product_id,
                                    # Never more than a third of the line, so a
                                    # transfer cannot imply a negative source.
                                    "q": max(
                                        1, int(line.quantity * rng.uniform(0.05, 0.3))
                                    ),
                                },
                            )
                    counts["transfers"] += 1

            # ------------------------------------------------- stock counts --
            for n in range(COUNTS_PER_COMPANY):
                warehouse = rng.choice(warehouses)
                lines = db.execute(
                    text(
                        """
                        SELECT i.product_id, i.quantity
                        FROM inventory i
                        JOIN products p ON p.id = i.product_id
                        WHERE i.warehouse_id = :w AND p.company_id = :c
                          AND i.quantity > 0
                        ORDER BY random()
                        LIMIT 12
                        """
                    ),
                    {"w": warehouse.id, "c": company.id},
                ).fetchall()
                if not lines:
                    continue

                age_days = rng.randint(0, 60)
                created = now - timedelta(days=age_days)
                status = _weighted(
                    [("approved", 60), ("pending", 25), ("rejected", 15)], rng
                )

                rec_id = str(uuid.uuid4())
                if not dry_run:
                    db.execute(
                        text(
                            """
                            INSERT INTO reconciliations
                                (id, company_id, warehouse_id, status, created_at)
                            VALUES (:id, :c, :w, :st, :cr)
                            """
                        ),
                        {
                            "id": rec_id,
                            "c": company.id,
                            "w": warehouse.id,
                            "st": status,
                            "cr": created,
                        },
                    )
                    for line in lines:
                        expected = int(line.quantity)
                        # Most lines agree. That is the point of a count: the
                        # exceptions are the information, and a report where
                        # everything is wrong tells you nothing.
                        if rng.random() < 0.7:
                            actual, reason = expected, None
                        else:
                            drift = max(1, int(expected * rng.uniform(0.01, 0.08)))
                            actual = max(0, expected + rng.choice([-drift, drift]))
                            reason = _weighted(DISCREPANCY_REASONS, rng)
                        db.execute(
                            text(
                                """
                                INSERT INTO reconciliation_items
                                    (id, reconciliation_id, product_id,
                                     expected_quantity, actual_quantity,
                                     discrepancy_reason)
                                VALUES (:id, :r, :p, :e, :a, :why)
                                """
                            ),
                            {
                                "id": str(uuid.uuid4()),
                                "r": rec_id,
                                "p": line.product_id,
                                "e": expected,
                                "a": actual,
                                "why": reason,
                            },
                        )
                counts["stock_counts"] += 1

            # ------------------------------------------------------ alerts --
            #
            # Derived from stock lines that are genuinely at or below their
            # reorder point, so every alert can be clicked through and checked.
            at_risk = db.execute(
                text(
                    """
                    -- reorder_point lives on inventory, not products: the
                    -- threshold is a property of a product IN A BUILDING, not
                    -- of the product itself. The same SKU can reasonably carry
                    -- a different reorder point in Mumbai than in Nagpur.
                    -- DISTINCT ON the product, not the stock line.
                    --
                    -- uq_alerts_one_open_per_subject allows exactly one open
                    -- alert per (company, type, subject) -- an operator wants
                    -- to be told once that a SKU is short, not once per
                    -- building. Selecting per inventory line produced two rows
                    -- for the same product low in two warehouses and the index
                    -- correctly refused the second. The worst line wins, so
                    -- the alert reports the site in most trouble.
                    SELECT DISTINCT ON (i.product_id)
                           i.product_id, i.quantity, p.name, p.sku,
                           i.reorder_point, w.name AS warehouse
                    FROM inventory i
                    JOIN products p ON p.id = i.product_id
                    JOIN warehouses w ON w.id = i.warehouse_id
                    WHERE p.company_id = :c
                      AND i.reorder_point > 0
                      AND i.quantity <= i.reorder_point
                    ORDER BY i.product_id, (i.reorder_point - i.quantity) DESC
                    LIMIT 12
                    """
                ),
                {"c": company.id},
            ).fetchall()

            for line in at_risk:
                out = line.quantity == 0
                alert_type = "out_of_stock" if out else "low_stock"

                # These three, and no others: ck_alerts_severity and
                # ck_alerts_status are CHECK constraints, so the schema is the
                # authority on the vocabulary rather than convention. An
                # invented "high"/"medium"/"active" is rejected at insert,
                # which is exactly what you want a constraint to do.
                severity = (
                    "critical"
                    if out
                    else (
                        "warning"
                        if line.quantity < line.reorder_point * 0.5
                        else "info"
                    )
                )
                status = _weighted(
                    [("open", 70), ("resolved", 20), ("dismissed", 10)], rng
                )
                created = now - timedelta(
                    days=rng.randint(0, 14), hours=rng.randint(0, 23)
                )

                if not dry_run:
                    db.execute(
                        text(
                            """
                            INSERT INTO alerts
                                (id, company_id, alert_type, severity, status,
                                 subject_type, subject_id, title, detail,
                                 created_at, resolved_at, dismissed_at)
                            VALUES (:id, :c, :t, :sev, :st, 'product', :sid,
                                    :title, CAST(:detail AS jsonb), :cr, :res, :dis)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "c": company.id,
                            "t": alert_type,
                            "sev": severity,
                            "st": status,
                            "sid": line.product_id,
                            "title": (
                                f"{line.name} is out of stock at {line.warehouse}"
                                if out
                                else f"{line.name} is below its reorder point at {line.warehouse}"
                            ),
                            "detail": (
                                '{"sku": "%s", "on_hand": %d, "reorder_point": %d,'
                                ' "warehouse": "%s"}'
                                % (
                                    line.sku,
                                    line.quantity,
                                    line.reorder_point,
                                    line.warehouse.replace('"', ""),
                                )
                            ),
                            "cr": created,
                            "res": created + timedelta(days=1)
                            if status == "resolved"
                            else None,
                            "dis": created + timedelta(hours=6)
                            if status == "dismissed"
                            else None,
                        },
                    )
                counts["alerts"] += 1

            print(
                f"  {company.name:<24} "
                f"transfers {counts['transfers']:>3}   "
                f"stock counts {counts['stock_counts']:>3}   "
                f"alerts {counts['alerts']:>3}"
            )

        if dry_run:
            db.rollback()
            print("\n  DRY RUN: nothing written.\n")
        else:
            db.commit()
            print("\n  Done.\n")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Clear and regenerate.")
    parser.add_argument("--dry-run", action="store_true", help="Write nothing.")
    args = parser.parse_args()

    print("\n  Seeding operational history")
    print("  " + "-" * 60)
    seed(reset=args.reset, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
