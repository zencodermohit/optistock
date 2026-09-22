"""Take one warehouse down to zero, through the ledger rather than around it.

WHY NOT AN UPDATE. Setting `inventory.quantity = 0` is one statement and it is
the wrong one. This system's whole claim is that stock never changes without a
movement recording it: the outbox, the relay, the consumers and the audit trail
all exist to make that true. A silent UPDATE leaves the quantity disagreeing
with the sum of its own movement history -- a contradiction that no screen
displays and that anyone who thinks to add up the ledger can find. Every line
zeroed here gets a real `manual_adjustment` movement first, so the history
still explains the number.

WHY NO DOMAIN EVENTS. The movements are written directly rather than through
InventoryService, which would stage `stock.moved` and `stock.depleted` for
every line. Emptying a warehouse of ninety-four lines would then raise
ninety-four depletion alerts at once and bury whatever the alerts page was
actually for. This is preparation, not trading -- the same reason
`backfill_history.py` writes sales without emitting events for them.

    python scripts/empty_warehouse.py "Mumbai Central Hub"
    python scripts/empty_warehouse.py "Mumbai Central Hub" --apply

Dry by default, and it names every line it would touch. This is the destructive
one; it should be boring to preview and deliberate to run.
"""

import argparse
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, insert, text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: F401,E402  -- registry
from app.core.config import settings  # noqa: E402
from app.modules.inventory.models import Inventory, InventoryMovement  # noqa: E402

#: Stamped on every movement this writes, so the adjustment is identifiable
#: later as preparation rather than as something the business did.
REFERENCE = "prep:empty-warehouse"


def empty(
    session: Session, warehouse_name: str, company_name: str | None, apply: bool
) -> dict:
    # A warehouse name is NOT an identifier here. Every tenant names its sites
    # for the cities it ships from, so two companies both having a "Mumbai
    # Central Hub" is the normal case rather than a collision. The first
    # version of this took `.first()` and silently emptied whichever row the
    # planner happened to return -- on a multi-tenant database, the one bug
    # this script must not have.
    matches = session.execute(
        text(
            """
            SELECT w.id, c.name
            FROM warehouses w
            JOIN companies c ON c.id = w.company_id
            WHERE w.name = :n AND (:company IS NULL OR c.name = :company)
            ORDER BY c.name
            """
        ),
        {"n": warehouse_name, "company": company_name},
    ).all()

    if not matches:
        return {"error": f"no warehouse named {warehouse_name!r} for that company"}
    if len(matches) > 1:
        owners = ", ".join(sorted(owner for _, owner in matches))
        return {
            "error": (
                f"{warehouse_name!r} exists for {len(matches)} companies "
                f"({owners}). Name one with --company."
            )
        }

    warehouse_id, owner = matches[0]

    lines = (
        session.query(Inventory)
        .filter(
            Inventory.warehouse_id == warehouse_id,
            Inventory.quantity != 0,
        )
        .all()
    )
    if not lines:
        return {"warehouse": warehouse_name, "company": owner, "note": "already empty"}

    units = sum(line.quantity for line in lines)
    summary = {
        "warehouse": warehouse_name,
        "company": owner,
        "stock_lines": len(lines),
        "units_removed": units,
    }
    if not apply:
        summary["mode"] = "dry run, nothing written"
        return summary

    now = datetime.now(timezone.utc)
    movements = [
        {
            "id": uuid.uuid4(),
            "inventory_id": line.id,
            "movement_type": "manual_adjustment",
            "quantity_change": -line.quantity,
            "quantity_after": 0,
            "reference_id": REFERENCE,
            "created_at": now,
        }
        for line in lines
    ]

    # Movements first. If the process dies between the two statements, a
    # movement with no corresponding change is a harmless orphan in the
    # history; a quantity with no movement is the contradiction this script
    # exists to avoid.
    session.execute(insert(InventoryMovement), movements)
    for line in lines:
        line.quantity = 0
        line.last_counted_at = now
    session.commit()

    summary["movements_written"] = len(movements)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("warehouse", help="exact warehouse name")
    parser.add_argument(
        "--company", help="required when two tenants share the warehouse name"
    )
    parser.add_argument(
        "--apply", action="store_true", help="write; without it, report only"
    )
    args = parser.parse_args()

    engine = create_engine(settings.DATABASE_URL)
    with Session(engine) as session:
        result = empty(session, args.warehouse, args.company, args.apply)
        for key, value in result.items():
            print(
                f"  {key:18} {value:,}"
                if isinstance(value, int)
                else f"  {key:18} {value}"
            )
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
