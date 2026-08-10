"""Read models for the screens that had none.

Four modules shipped an API long before they shipped a page, and all four
return the same thing when you ask them for a list: foreign keys. That is
correct for an API and useless for a person — a supplier row reading
`3f2b…/a91c…` is not a supplier row.

Each function here does the same job the purchase-order pipeline and the sales
ledger already do: resolve the names once on the server, and add the one or two
derived figures the screen exists to show. They live together because they are
the same shape of problem, and keeping them in one place makes it obvious when
a fifth one is copying the fourth rather than doing something new.

The rule they share: every query filters on company_id, and where a row has no
company_id of its own it is reached through one that does.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog
from app.modules.products.models import Product
from app.modules.purchase_orders.models import PurchaseOrder
from app.modules.reconciliation.models import Reconciliation, ReconciliationItem
from app.modules.suppliers.models import Supplier
from app.modules.transfers.models import Transfer, TransferItem
from app.modules.users.models import User
from app.modules.warehouses.models import Warehouse


def _names(db: Session, model, company_id: UUID) -> Dict[UUID, str]:
    """id -> name for one tenant's rows of a simple named table."""
    return dict(
        db.query(model.id, model.name).filter(model.company_id == company_id).all()
    )


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
def supplier_scorecard(db: Session, company_id: UUID) -> List[Dict[str, Any]]:
    """Suppliers with what you have actually bought from them.

    `reliability_score` has sat on this table since the schema was written and
    has never been shown to anyone, which makes it a number nobody can check.
    Putting it beside the real order history is what turns it from a claim into
    a claim with evidence — and where the two disagree, the history wins.

    Delivery rate is counted from orders, not asserted: how many of this
    supplier's orders reached `delivered`, out of how many were raised.
    """
    orders = (
        db.query(
            PurchaseOrder.supplier_id.label("supplier_id"),
            func.count(PurchaseOrder.id).label("orders"),
            func.coalesce(func.sum(PurchaseOrder.total_amount), 0).label("spend"),
            func.sum(case((PurchaseOrder.status == "delivered", 1), else_=0)).label(
                "delivered"
            ),
            func.max(PurchaseOrder.created_at).label("last_order_at"),
        )
        .filter(PurchaseOrder.company_id == company_id)
        .group_by(PurchaseOrder.supplier_id)
        .subquery()
    )

    rows = (
        db.query(
            Supplier.id,
            Supplier.name,
            Supplier.contact_email,
            Supplier.reliability_score,
            Supplier.is_active,
            orders.c.orders,
            orders.c.spend,
            orders.c.delivered,
            orders.c.last_order_at,
        )
        # Outer, because a supplier you have never ordered from is a real row —
        # often the newest one, and the one somebody is about to use.
        .outerjoin(orders, orders.c.supplier_id == Supplier.id)
        .filter(Supplier.company_id == company_id)
        .order_by(orders.c.spend.desc().nullslast(), Supplier.name)
        .all()
    )

    return [
        {
            "id": str(row.id),
            "name": row.name,
            "contact_email": row.contact_email,
            "reliability_score": float(row.reliability_score or 0),
            "is_active": row.is_active,
            "orders": int(row.orders or 0),
            "spend": float(row.spend or 0),
            "delivered": int(row.delivered or 0),
            "last_order_at": row.last_order_at,
            # None rather than 0 when nothing has been ordered: a delivery rate
            # of "no orders" is not a rate of zero, and showing 0% would libel
            # a supplier for the crime of being new.
            "delivery_rate": (
                round(int(row.delivered or 0) / int(row.orders), 3)
                if row.orders
                else None
            ),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------
def transfer_board(
    db: Session, company_id: UUID, limit: int = 100
) -> List[Dict[str, Any]]:
    """Stock moving between your own warehouses, newest first.

    A transfer is the one movement that is neither a purchase nor a sale: stock
    leaves one shelf and lands on another, and in between it belongs to neither.
    That in-between is the whole reason the screen exists, so the shipped and
    received timestamps are carried rather than collapsed into a status word.
    """
    transfers = (
        db.query(Transfer)
        .filter(Transfer.company_id == company_id)
        .order_by(Transfer.created_at.desc())
        .limit(limit)
        .all()
    )
    if not transfers:
        return []

    warehouses = _names(db, Warehouse, company_id)
    products = {
        row.id: (row.sku, row.name)
        for row in db.query(Product.id, Product.sku, Product.name)
        .filter(Product.company_id == company_id)
        .all()
    }

    items_by_transfer: Dict[UUID, List[TransferItem]] = {}
    for item in (
        db.query(TransferItem)
        .filter(TransferItem.transfer_id.in_([t.id for t in transfers]))
        .all()
    ):
        items_by_transfer.setdefault(item.transfer_id, []).append(item)

    return [
        {
            "id": str(transfer.id),
            "status": transfer.status,
            "created_at": transfer.created_at,
            "shipped_at": transfer.shipped_at,
            "received_at": transfer.received_at,
            "source_name": warehouses.get(transfer.source_warehouse_id, "Unknown"),
            "destination_name": warehouses.get(
                transfer.destination_warehouse_id, "Unknown"
            ),
            "items": [
                {
                    "sku": products.get(item.product_id, ("?", "?"))[0],
                    "product_name": products.get(item.product_id, ("?", "?"))[1],
                    "quantity": item.quantity,
                }
                for item in items_by_transfer.get(transfer.id, [])
            ],
            "units": sum(
                item.quantity for item in items_by_transfer.get(transfer.id, [])
            ),
        }
        for transfer in transfers
    ]


# ---------------------------------------------------------------------------
# Reconciliations
# ---------------------------------------------------------------------------
def reconciliation_board(
    db: Session, company_id: UUID, limit: int = 100
) -> List[Dict[str, Any]]:
    """Cycle counts, with the variance worked out.

    A reconciliation is a disagreement between the system and a shelf, and the
    only number anyone wants is the size of that disagreement. Counted here
    rather than in the browser so the figure the approver sees is the figure the
    approval is recorded against.

    Both directions are kept. A count that is 40 short and 40 over is not a
    clean count that nets to zero — it is two errors, and netting them would
    hide both.
    """
    recons = (
        db.query(Reconciliation)
        .filter(Reconciliation.company_id == company_id)
        .order_by(Reconciliation.created_at.desc())
        .limit(limit)
        .all()
    )
    if not recons:
        return []

    warehouses = _names(db, Warehouse, company_id)
    products = {
        row.id: (row.sku, row.name)
        for row in db.query(Product.id, Product.sku, Product.name)
        .filter(Product.company_id == company_id)
        .all()
    }

    items_by_recon: Dict[UUID, List[ReconciliationItem]] = {}
    for item in (
        db.query(ReconciliationItem)
        .filter(ReconciliationItem.reconciliation_id.in_([r.id for r in recons]))
        .all()
    ):
        items_by_recon.setdefault(item.reconciliation_id, []).append(item)

    board = []
    for recon in recons:
        items = items_by_recon.get(recon.id, [])
        lines = [
            {
                "sku": products.get(item.product_id, ("?", "?"))[0],
                "product_name": products.get(item.product_id, ("?", "?"))[1],
                "expected": item.expected_quantity,
                "actual": item.actual_quantity,
                "variance": item.actual_quantity - item.expected_quantity,
                "reason": item.discrepancy_reason,
            }
            for item in items
        ]
        board.append(
            {
                "id": str(recon.id),
                "status": recon.status,
                "created_at": recon.created_at,
                "warehouse_name": warehouses.get(recon.warehouse_id, "Unknown"),
                "items": lines,
                "counted": len(lines),
                "discrepancies": sum(1 for line in lines if line["variance"] != 0),
                "units_short": sum(
                    -line["variance"] for line in lines if line["variance"] < 0
                ),
                "units_over": sum(
                    line["variance"] for line in lines if line["variance"] > 0
                ),
            }
        )
    return board


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
def audit_trail(
    db: Session,
    company_id: UUID,
    entity_name: Optional[str] = None,
    action: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> Dict[str, Any]:
    """The compliance trail, with the actor resolved to a person.

    The stored row keeps user_id, which is right — an email address changes and
    an audit row must not. But a UUID in the "who" column of a compliance screen
    is unreadable, so the email is resolved at read time and falls back to
    "deleted user" rather than to a blank: user_id is ON DELETE SET NULL, and
    the record of what they did outlives the account.
    """
    query = db.query(AuditLog).filter(AuditLog.company_id == company_id)
    if entity_name:
        query = query.filter(AuditLog.entity_name == entity_name)
    if action:
        query = query.filter(AuditLog.action == action)

    total = query.count()
    rows = (
        query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()
    )

    actors = dict(
        db.query(User.id, User.email).filter(User.company_id == company_id).all()
    )

    # The distinct values actually present, so the filter offers what exists
    # instead of a hardcoded list that drifts from the data.
    entities = [
        value
        for (value,) in db.query(AuditLog.entity_name)
        .filter(AuditLog.company_id == company_id)
        .distinct()
        .order_by(AuditLog.entity_name)
        .all()
    ]
    actions = [
        value
        for (value,) in db.query(AuditLog.action)
        .filter(AuditLog.company_id == company_id)
        .distinct()
        .order_by(AuditLog.action)
        .all()
    ]

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "entities": entities,
        "actions": actions,
        "data": [
            {
                "id": str(row.id),
                "entity_name": row.entity_name,
                "entity_id": str(row.entity_id),
                "action": row.action,
                "timestamp": row.timestamp,
                "actor": (
                    actors.get(row.user_id, "deleted user")
                    if row.user_id
                    else "system"
                ),
                "old_values": row.old_values,
                "new_values": row.new_values,
            }
            for row in rows
        ],
    }
