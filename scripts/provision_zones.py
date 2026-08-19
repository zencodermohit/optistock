"""Give every warehouse its zones, on a database that already has warehouses.

The zones exist as a data migration (b7d3e1f95a24), and that was the wrong home
for them. A migration runs once, at deploy, against whatever is in the database
at that moment -- and on a fresh deployment that is nothing. It looped over the
warehouses it found, found none, inserted nothing, and reported success. Every
warehouse created afterwards by seed_db.py therefore had no zones at all, and
the floor plan said "No zones configured for this warehouse" forever.

Nothing was broken in the screen. The screen was right.

Locally the bug is invisible, which is why it survived: the warehouses were
already there when that migration first ran, so it did populate them. A
migration whose effect depends on when it happened to run relative to seeding
cannot be trusted to have run at all.

So this is a script rather than another migration, and it is IDEMPOTENT: it
skips any warehouse that already has zones, which means it is safe to run on a
new deployment, on an existing one, and twice by mistake.

    python scripts/provision_zones.py --dry-run
    python scripts/provision_zones.py

The capacity arithmetic is lifted from the migration deliberately rather than
improved, so a warehouse provisioned here is indistinguishable from one
provisioned there.
"""

import argparse
import sys
import uuid
from pathlib import Path

# Same preamble as the other scripts here: `python scripts/x.py` puts scripts/
# on sys.path, not the project root, so `app` is not importable without this.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402

import app.models  # noqa: F401,E402  — completes the ORM registry
from app.core.database import SessionLocal  # noqa: E402

#: Code, display name, and the Product.category it claims. The category is the
#: join that decides which stock lines live in the zone, so these strings must
#: match the catalogue exactly -- a typo produces an empty zone, not an error.
ZONES = [
    ("A", "Electronics", "Electronics"),
    ("B", "Furniture", "Furniture"),
    ("C", "Office Supplies", "Office Supplies"),
    ("D", "Networking", "Networking"),
    ("E", "Safety & PPE", "Safety & PPE"),
    ("F", "Packaging", "Packaging"),
]

#: What a healthy building runs at. A warehouse is not meant to be full -- you
#: cannot receive into a full one -- so capacity is sized to leave headroom.
TARGET_UTILISATION = 0.76

#: How much of a zone's size follows what it actually holds, versus an equal
#: share of the floor. Purely proportional makes empty categories vanish to a
#: sliver; purely equal makes the floor plan say nothing about the business.
PROPORTIONAL_WEIGHT = 0.55


def provision(dry_run: bool = False) -> int:
    db = SessionLocal()
    created = 0
    try:
        warehouses = db.execute(
            text(
                """
                SELECT w.id, w.company_id, w.name, w.capacity_units
                FROM warehouses w
                WHERE NOT EXISTS (
                    SELECT 1 FROM warehouse_zones z WHERE z.warehouse_id = w.id
                )
                ORDER BY w.name
                """
            )
        ).fetchall()

        if not warehouses:
            print("  Every warehouse already has zones. Nothing to do.")
            return 0

        for w in warehouses:
            # What the building actually holds, per category. This is what makes
            # the floor plan describe a real business rather than six equal
            # rectangles: a site full of furniture gets a big Zone B.
            held = dict(
                db.execute(
                    text(
                        """
                        SELECT p.category, COALESCE(SUM(i.quantity), 0)
                        FROM inventory i
                        JOIN products p ON p.id = i.product_id
                        WHERE i.warehouse_id = :wid
                        GROUP BY p.category
                        """
                    ),
                    {"wid": w.id},
                ).fetchall()
            )
            total_held = sum(held.values())

            capacity = (
                max(int(total_held / TARGET_UTILISATION), 1)
                if total_held > 0
                else int(w.capacity_units or 1000)
            )

            if not dry_run:
                db.execute(
                    text("UPDATE warehouses SET capacity_units = :c WHERE id = :wid"),
                    {"c": capacity, "wid": w.id},
                )

            equal_share = capacity / len(ZONES)
            for code, name, category in ZONES:
                units = int(held.get(category, 0))
                proportional = (units / total_held * capacity) if total_held > 0 else 0
                allowance = (
                    PROPORTIONAL_WEIGHT * proportional
                    + (1 - PROPORTIONAL_WEIGHT) * equal_share
                )
                if not dry_run:
                    db.execute(
                        text(
                            """
                            INSERT INTO warehouse_zones
                                (id, company_id, warehouse_id, code, name,
                                 category, capacity_units)
                            VALUES (:id, :cid, :wid, :code, :name, :cat, :cap)
                            """
                        ),
                        {
                            "id": str(uuid.uuid4()),
                            "cid": w.company_id,
                            "wid": w.id,
                            "code": code,
                            "name": name,
                            "cat": category,
                            # At least one, so utilisation can never divide by
                            # zero on an empty zone.
                            "cap": max(int(allowance), 1),
                        },
                    )
                created += 1

            print(f"  {w.name:<28} {len(ZONES)} zones, capacity {capacity:,}")

        if dry_run:
            db.rollback()
            print(f"\n  DRY RUN: would create {created} zones. Nothing written.")
        else:
            db.commit()
            print(f"\n  Created {created} zones across {len(warehouses)} warehouses.")
        return created
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be created without writing anything.",
    )
    args = parser.parse_args()

    print("\n  Provisioning warehouse zones")
    print("  " + "-" * 56)
    provision(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
