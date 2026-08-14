"""The Inventory module's two layers: the network, and one warehouse inside it.

This is a physical view, deliberately. Analytics answers how the business is
doing; this answers where the stock IS and which part of which building needs
somebody to walk over to it. Nothing here reports revenue, margin or ranking —
those questions have their own screen and duplicating them would make two pages
that disagree.

Two read models:

    network         every warehouse as a node, plus the transfers moving stock
                    between them. The question is "which site is struggling".
    command_center  one warehouse broken into zones, with what is happening in
                    it right now. The question is "which zone is overloaded".

Zone membership is derived by product category rather than stored per line —
see zone_models.WarehouseZone for why.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.alerts.models import STATUS_OPEN, Alert
from app.modules.analytics.dashboard import _health
from app.modules.events.models import EventOutbox
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.reconciliation.models import Reconciliation
from app.modules.transfers.models import Transfer, TransferItem
from app.modules.warehouses.models import Warehouse
from app.modules.warehouses.zone_models import WarehouseZone

#: Where a zone stops being comfortable and starts being a problem. Ninety per
#: cent is the point at which a forklift can no longer be sure of a free slot,
#: which is what "full" means to the person on the floor.
ZONE_WARN = 0.70
ZONE_CRITICAL = 0.90

#: A site's overall health band. Matches the language on the network legend.
HEALTHY = 80
MODERATE = 60


def _stock_rows(db: Session, company_id: UUID, warehouse_id: Optional[UUID] = None):
    """Stock on hand with the two things every caller here needs: what it is
    worth, and which category — and therefore which zone — it sits in."""
    query = (
        db.query(
            Inventory.id,
            Inventory.product_id,
            Inventory.warehouse_id,
            Inventory.quantity,
            Inventory.reorder_point,
            Product.sku,
            Product.name.label("product_name"),
            Product.category,
            Product.unit_cost,
        )
        .join(Product, Product.id == Inventory.product_id)
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .filter(Warehouse.company_id == company_id, Product.company_id == company_id)
    )
    if warehouse_id:
        query = query.filter(Inventory.warehouse_id == warehouse_id)
    return query.all()


def _band(score: Optional[int]) -> str:
    if score is None:
        return "unknown"
    if score >= HEALTHY:
        return "healthy"
    if score >= MODERATE:
        return "moderate"
    return "at_risk"


# ---------------------------------------------------------------------------
# Layer 1 — the network
# ---------------------------------------------------------------------------
def network(db: Session, company_id: UUID) -> Dict[str, Any]:
    """Every site as a node, and the stock moving between them.

    The edges are real transfers rather than a decorative mesh. A line between
    two buildings means something left one and has not yet arrived at the other,
    which is the only relationship between two warehouses worth drawing.
    """
    warehouses = (
        db.query(Warehouse)
        .filter(Warehouse.company_id == company_id)
        .order_by(Warehouse.name)
        .all()
    )
    if not warehouses:
        return {"nodes": [], "edges": [], "summary": {}, "alerts": [], "transfers": []}

    stock = _stock_rows(db, company_id)
    alerts_by_wh = dict(
        db.query(Inventory.warehouse_id, func.count(Alert.id))
        .join(Alert, Alert.subject_id == Inventory.id)
        .filter(
            Alert.company_id == company_id,
            Alert.status == STATUS_OPEN,
            Alert.subject_type == "inventory",
        )
        .group_by(Inventory.warehouse_id)
        .all()
    )
    # Orders still owed from each site: sales that have not completed.
    open_orders = dict(
        db.query(Transfer.source_warehouse_id, func.count(Transfer.id))
        .filter(
            Transfer.company_id == company_id,
            Transfer.status.notin_(["completed", "cancelled"]),
        )
        .group_by(Transfer.source_warehouse_id)
        .all()
    )

    nodes = []
    for wh in warehouses:
        lines = [r for r in stock if r.warehouse_id == wh.id]
        units = sum(r.quantity for r in lines)
        out = sum(1 for r in lines if r.quantity <= 0)
        low = sum(
            1 for r in lines if r.reorder_point > 0 and 0 < r.quantity <= r.reorder_point
        )
        alerts = int(alerts_by_wh.get(wh.id, 0))
        health = _health(len(lines), out, low, alerts)
        capacity = int(wh.capacity_units or 0)

        nodes.append(
            {
                "id": str(wh.id),
                "name": wh.name,
                "location_code": wh.location_code,
                "capacity_units": capacity,
                "units_held": units,
                "utilisation": round(min(units / capacity, 1.5), 4) if capacity else None,
                "inventory_value": round(
                    sum(float(r.unit_cost or 0) * r.quantity for r in lines), 2
                ),
                "stock_lines": len(lines),
                "low_lines": low,
                "out_lines": out,
                "open_alerts": alerts,
                "active_orders": int(open_orders.get(wh.id, 0)),
                "health": health["score"],
                "band": _band(health["score"]),
                **{k: v for k, v in health.items() if k != "score"},
            }
        )

    # Edges: stock in flight. Only transfers that have left and not landed --
    # a completed transfer is history, not a line on a live map.
    in_flight = (
        db.query(Transfer)
        .filter(
            Transfer.company_id == company_id,
            Transfer.status.notin_(["completed", "cancelled"]),
        )
        .all()
    )
    units_by_transfer = dict(
        db.query(TransferItem.transfer_id, func.coalesce(func.sum(TransferItem.quantity), 0))
        .filter(TransferItem.transfer_id.in_([t.id for t in in_flight] or [None]))
        .group_by(TransferItem.transfer_id)
        .all()
    )
    edges = [
        {
            "id": str(t.id),
            "from": str(t.source_warehouse_id),
            "to": str(t.destination_warehouse_id),
            "units": int(units_by_transfer.get(t.id, 0)),
            "status": t.status,
            "shipped_at": t.shipped_at,
        }
        for t in in_flight
    ]

    # Recent movements between sites, whatever their state.
    names = {str(w.id): w.name for w in warehouses}
    recent = (
        db.query(Transfer)
        .filter(Transfer.company_id == company_id)
        .order_by(Transfer.created_at.desc())
        .limit(6)
        .all()
    )

    # Inventory accuracy, measured from the counts people actually did. None
    # rather than a flattering 100% when nobody has counted anything -- an
    # unmeasured shelf is not an accurate one.
    counted = (
        db.query(
            func.count(Reconciliation.id),
            func.sum(case((Reconciliation.status == "approved", 1), else_=0)),
        )
        .filter(Reconciliation.company_id == company_id)
        .one()
    )

    bands = {"healthy": 0, "moderate": 0, "at_risk": 0, "unknown": 0}
    for node in nodes:
        bands[node["band"]] += 1

    return {
        "nodes": nodes,
        "edges": edges,
        "summary": {
            "sites": len(nodes),
            "units_held": sum(n["units_held"] for n in nodes),
            "inventory_value": round(sum(n["inventory_value"] for n in nodes), 2),
            "stock_lines": sum(n["stock_lines"] for n in nodes),
            "utilisation": (
                round(
                    sum(n["units_held"] for n in nodes)
                    / max(sum(n["capacity_units"] for n in nodes), 1),
                    4,
                )
            ),
            "in_flight": len(edges),
            "low_lines": sum(n["low_lines"] for n in nodes),
            "out_lines": sum(n["out_lines"] for n in nodes),
            "bands": bands,
            "counts_recorded": int(counted[0] or 0),
            "counts_approved": int(counted[1] or 0),
        },
        "transfers": [
            {
                "id": str(t.id),
                "from": names.get(str(t.source_warehouse_id), "Unknown"),
                "to": names.get(str(t.destination_warehouse_id), "Unknown"),
                "units": int(units_by_transfer.get(t.id, 0)),
                "status": t.status,
                "created_at": t.created_at,
            }
            for t in recent
        ],
        "alerts": _network_alerts(db, company_id, nodes),
    }


def _network_alerts(db, company_id, nodes) -> List[Dict[str, Any]]:
    """The four things worth waking somebody for, counted across the network.

    Rolled up rather than listed: a manager looking at five buildings wants
    "312 items running low across 3 warehouses", not 312 rows.
    """
    low = sum(n["low_lines"] for n in nodes)
    out = sum(n["out_lines"] for n in nodes)
    low_sites = sum(1 for n in nodes if n["low_lines"] > 0)
    out_sites = sum(1 for n in nodes if n["out_lines"] > 0)

    overloaded = (
        db.query(func.count(WarehouseZone.id))
        .filter(WarehouseZone.company_id == company_id)
        .scalar()
    )
    zones = _zone_rows(db, company_id)
    over = [z for z in zones if z["utilisation"] and z["utilisation"] >= ZONE_CRITICAL]

    return [
        {
            "key": "out_of_stock",
            "severity": "critical",
            "count": out,
            "title": f"{out} lines out of stock",
            "detail": f"across {out_sites} warehouse{'s' if out_sites != 1 else ''}",
        },
        {
            "key": "low_stock",
            "severity": "warning",
            "count": low,
            "title": f"{low} lines below reorder point",
            "detail": f"across {low_sites} warehouse{'s' if low_sites != 1 else ''}",
        },
        {
            "key": "zones_full",
            "severity": "warning",
            "count": len(over),
            "title": f"{len(over)} zones over {int(ZONE_CRITICAL * 100)}% full",
            "detail": f"of {overloaded} zones on the network",
        },
    ]


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------
def _zone_rows(
    db: Session, company_id: UUID, warehouse_id: Optional[UUID] = None
) -> List[Dict[str, Any]]:
    """Every zone with what is actually standing in it.

    The join is category to category. A stock line is in Zone B because the
    product is furniture, not because a column says so.
    """
    zones = db.query(WarehouseZone).filter(WarehouseZone.company_id == company_id)
    if warehouse_id:
        zones = zones.filter(WarehouseZone.warehouse_id == warehouse_id)
    zones = zones.order_by(WarehouseZone.code).all()
    if not zones:
        return []

    stock = _stock_rows(db, company_id, warehouse_id)
    alert_lines = {
        row[0]
        for row in db.query(Alert.subject_id)
        .filter(
            Alert.company_id == company_id,
            Alert.status == STATUS_OPEN,
            Alert.subject_type == "inventory",
        )
        .all()
    }

    rows = []
    for zone in zones:
        lines = [
            r
            for r in stock
            if r.warehouse_id == zone.warehouse_id and r.category == zone.category
        ]
        units = sum(r.quantity for r in lines)
        capacity = int(zone.capacity_units or 0)
        utilisation = round(units / capacity, 4) if capacity else None

        rows.append(
            {
                "id": str(zone.id),
                "warehouse_id": str(zone.warehouse_id),
                "code": zone.code,
                "name": zone.name,
                "category": zone.category,
                "capacity_units": capacity,
                "units_held": units,
                "available": max(capacity - units, 0),
                "utilisation": utilisation,
                "state": (
                    "critical"
                    if utilisation and utilisation >= ZONE_CRITICAL
                    else "warning"
                    if utilisation and utilisation >= ZONE_WARN
                    else "ok"
                ),
                "inventory_value": round(
                    sum(float(r.unit_cost or 0) * r.quantity for r in lines), 2
                ),
                "stock_lines": len(lines),
                "low_lines": sum(
                    1
                    for r in lines
                    if r.reorder_point > 0 and 0 < r.quantity <= r.reorder_point
                ),
                "out_lines": sum(1 for r in lines if r.quantity <= 0),
                "open_alerts": sum(1 for r in lines if r.id in alert_lines),
                # The lines a person would actually walk to, worst first.
                "attention": [
                    {
                        "sku": r.sku,
                        "product_name": r.product_name,
                        "quantity": r.quantity,
                        "reorder_point": r.reorder_point,
                        "state": "out" if r.quantity <= 0 else "low",
                    }
                    for r in sorted(lines, key=lambda r: r.quantity)
                    if r.quantity <= 0
                    or (r.reorder_point > 0 and r.quantity <= r.reorder_point)
                ][:8],
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Layer 2 — one warehouse
# ---------------------------------------------------------------------------
def command_center(
    db: Session, company_id: UUID, warehouse_id: UUID
) -> Optional[Dict[str, Any]]:
    """One building: its zones, its pressure, and what is happening in it now."""
    warehouse = (
        db.query(Warehouse)
        .filter(Warehouse.id == warehouse_id, Warehouse.company_id == company_id)
        .first()
    )
    if warehouse is None:
        return None

    zones = _zone_rows(db, company_id, warehouse_id)
    stock = _stock_rows(db, company_id, warehouse_id)
    units = sum(r.quantity for r in stock)
    capacity = int(warehouse.capacity_units or 0)

    # What is moving, in and out.
    inbound = (
        db.query(Transfer)
        .filter(
            Transfer.company_id == company_id,
            Transfer.destination_warehouse_id == warehouse_id,
            Transfer.status.notin_(["completed", "cancelled"]),
        )
        .count()
    )
    outbound = (
        db.query(Transfer)
        .filter(
            Transfer.company_id == company_id,
            Transfer.source_warehouse_id == warehouse_id,
            Transfer.status.notin_(["completed", "cancelled"]),
        )
        .count()
    )
    counts_open = (
        db.query(Reconciliation)
        .filter(
            Reconciliation.company_id == company_id,
            Reconciliation.warehouse_id == warehouse_id,
            Reconciliation.status == "pending",
        )
        .count()
    )

    # The live feed. Real domain events from the outbox rather than invented
    # worker activity -- every row here is something that actually happened,
    # with the sequence number that proves where it sat in the order.
    since = datetime.now(timezone.utc) - timedelta(days=7)
    events = (
        db.query(EventOutbox)
        .filter(
            EventOutbox.company_id == company_id,
            EventOutbox.occurred_at >= since,
        )
        .order_by(EventOutbox.sequence.desc())
        .limit(25)
        .all()
    )

    return {
        "warehouse": {
            "id": str(warehouse.id),
            "name": warehouse.name,
            "location_code": warehouse.location_code,
            "capacity_units": capacity,
            "units_held": units,
            "available": max(capacity - units, 0),
            "utilisation": round(units / capacity, 4) if capacity else None,
            "inventory_value": round(
                sum(float(r.unit_cost or 0) * r.quantity for r in stock), 2
            ),
            "stock_lines": len(stock),
        },
        "zones": zones,
        "operations": {
            "inbound_transfers": inbound,
            "outbound_transfers": outbound,
            "counts_awaiting_review": counts_open,
            "zones_critical": sum(1 for z in zones if z["state"] == "critical"),
            "zones_warning": sum(1 for z in zones if z["state"] == "warning"),
            "lines_low": sum(z["low_lines"] for z in zones),
            "lines_out": sum(z["out_lines"] for z in zones),
        },
        "feed": [
            {
                "sequence": e.sequence,
                "type": e.event_type,
                "aggregate": e.aggregate_type,
                "payload": e.payload,
                "at": e.occurred_at,
            }
            for e in events
        ],
    }
