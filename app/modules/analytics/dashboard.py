"""Everything the Analytics screen shows, in one request.

The page asks a single question -- "how is the business doing" -- and answering
it with eight round trips would mean eight loading states resolving at eight
different moments. One read model, one request, one render.

Three figures here are DERIVED rather than stored, and each one carries an
assumption worth stating out loud, because a number whose definition is hidden
is a number nobody can argue with:

    dead inventory     stock that has not sold in DEAD_STOCK_DAYS. There is no
                       "dead" flag in the schema; this is measured from the
                       absence of sales, which is the only honest way to get it.
    turnover           cost of goods sold over the window, annualised, over the
                       inventory value held now. Proper turnover uses AVERAGE
                       inventory across the period, and this system keeps no
                       historical stock snapshots -- so current value stands in
                       for the average. Stated on the page.
    health score       a composite. Its formula is published beside the table
                       rather than presented as an oracle, and every input is a
                       column the reader can already see.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.alerts.models import STATUS_OPEN, Alert
from app.modules.analytics.projections import recent_metrics
from app.modules.analytics.stockout import stockout_risks
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.purchase_orders.models import PurchaseOrder
from app.modules.sales.models import Sale, SaleItem
from app.modules.warehouses.models import Warehouse

#: A line with no sale in this many days is dead stock. Two months, and it sits
#: inside the sales history actually available, so the figure is measured
#: rather than extrapolated.
DEAD_STOCK_DAYS = 60

#: Cover beyond this is not healthy stock, it is money on a shelf.
EXCESS_COVER_DAYS = 180

#: The urgency bands. Chosen against supplier lead times rather than round
#: numbers -- under three days is inside nobody's turnaround.
RISK_BANDS = [
    ("critical", "0-3 days", 0, 3),
    ("high", "4-7 days", 3, 7),
    ("medium", "8-14 days", 7, 14),
    ("low", "15+ days", 14, float("inf")),
]


def _health(lines: int, out: int, low: int, alerts: int) -> Dict[str, Any]:
    """A warehouse's health, as a number with its working shown.

    Composite scores are usually a way of hiding a judgement. This one is
    published: three penalties, each weighted by how much it actually costs the
    business, applied to a base of 100.

    Out-of-stock is weighted heaviest because it is the failure that loses a
    sale outright. Below-reorder is a warning rather than a loss, so it costs
    less than half as much. Open alerts are capped, because a warehouse with
    twenty alerts is not four times worse than one with five -- past a point it
    is the same message repeated.

    The components come back with the score so the table can show both, and so
    "why is Delhi 81?" has an answer that is not "because the algorithm said so".
    """
    if lines == 0:
        return {"score": None, "out_penalty": 0, "low_penalty": 0, "alert_penalty": 0}

    out_penalty = 60 * (out / lines)
    low_penalty = 25 * (low / lines)
    alert_penalty = 15 * min(alerts / 5, 1.0)
    score = max(0, round(100 - out_penalty - low_penalty - alert_penalty))

    return {
        "score": score,
        "out_penalty": round(out_penalty, 1),
        "low_penalty": round(low_penalty, 1),
        "alert_penalty": round(alert_penalty, 1),
    }


def _trading_series(
    db: Session,
    company_id: UUID,
    days: int,
    warehouse_id: Optional[UUID],
):
    """Daily revenue, orders and units — for the whole company or for one site.

    Two paths, and the reason is a real limitation rather than a preference.
    `daily_metrics` is the CQRS read model the event consumers maintain, and it
    is keyed on (company_id, metric_date) with NO warehouse dimension. It cannot
    answer "revenue for Mumbai" at any price.

    So an unfiltered page reads the projection, which is what it is for and what
    makes the common case fast. A site-filtered page falls back to grouping the
    sales themselves. Both return the same shape and both fill missing days with
    zero, because a chart that skips quiet days draws a straight line across
    them and reports trading that never happened.

    The source comes back with the data so the page can say which one it used.
    Adding warehouse_id to the projection would remove the fork, at the cost of
    a migration, a consumer change and a backfill -- worth doing if this filter
    becomes a common path, and not worth guessing at now.
    """
    if warehouse_id is None:
        return recent_metrics(db, company_id, days=days), "projection"

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)

    # Revenue and order count come from the sale headers. Joining the items in
    # here would multiply each header by its line count and inflate revenue.
    headers = {
        row.day: row
        for row in db.query(
            func.date(Sale.created_at).label("day"),
            func.coalesce(func.sum(Sale.total_amount), 0).label("revenue"),
            func.count(Sale.id).label("orders"),
        )
        .filter(
            Sale.company_id == company_id,
            Sale.source_warehouse_id == warehouse_id,
            func.date(Sale.created_at) >= start,
            func.date(Sale.created_at) <= end,
        )
        .group_by(func.date(Sale.created_at))
        .all()
    }

    # Units need the items, so they are counted separately and merged.
    units = dict(
        db.query(
            func.date(Sale.created_at),
            func.coalesce(func.sum(SaleItem.quantity), 0),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.company_id == company_id,
            Sale.source_warehouse_id == warehouse_id,
            func.date(Sale.created_at) >= start,
            func.date(Sale.created_at) <= end,
        )
        .group_by(func.date(Sale.created_at))
        .all()
    )

    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = headers.get(day)
        series.append(
            {
                "date": day.isoformat(),
                "revenue": float(row.revenue) if row else 0.0,
                "orders": int(row.orders) if row else 0,
                "units_sold": int(units.get(day, 0)),
                "stock_movements": 0,
                "units_received": 0,
            }
        )
    return series, "sales"


def analytics(
    db: Session,
    company_id: UUID,
    days: int = 30,
    warehouse_id: Optional[UUID] = None,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    dead_cutoff = now - timedelta(days=DEAD_STOCK_DAYS)

    # ---- Stock on hand, valued -------------------------------------------
    stock_q = (
        db.query(
            Inventory.product_id,
            Inventory.warehouse_id,
            Inventory.quantity,
            Inventory.reorder_point,
            Product.unit_cost,
            Warehouse.name.label("warehouse_name"),
        )
        .join(Product, Product.id == Inventory.product_id)
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .filter(Warehouse.company_id == company_id, Product.company_id == company_id)
    )
    if warehouse_id:
        stock_q = stock_q.filter(Inventory.warehouse_id == warehouse_id)
    stock = stock_q.all()

    inventory_value = sum(float(r.unit_cost or 0) * r.quantity for r in stock)

    # ---- Which lines have moved recently ----------------------------------
    # Keyed on (product, warehouse) because that is the grain stock lives at:
    # a product selling in Mumbai and sitting still in Delhi is dead in Delhi.
    sold_recently = {
        (str(pid), str(wid))
        for pid, wid in db.query(SaleItem.product_id, Sale.source_warehouse_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(Sale.company_id == company_id, Sale.created_at >= dead_cutoff)
        .distinct()
        .all()
    }

    dead_lines = [
        r
        for r in stock
        if r.quantity > 0
        and (str(r.product_id), str(r.warehouse_id)) not in sold_recently
    ]
    dead_value = sum(float(r.unit_cost or 0) * r.quantity for r in dead_lines)

    # ---- Cost of goods sold across the window ------------------------------
    cogs = (
        db.query(func.coalesce(func.sum(SaleItem.quantity * Product.unit_cost), 0))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .join(Product, Product.id == SaleItem.product_id)
        .filter(Sale.company_id == company_id, Sale.created_at >= window_start)
        .scalar()
        or 0
    )
    # Annualised, and over CURRENT inventory rather than average inventory --
    # the system keeps no historical stock snapshots. The page says so.
    turnover = (
        round((float(cogs) / days * 365) / inventory_value, 2)
        if inventory_value > 0 and days > 0
        else None
    )

    # ---- Stockout risk, in the bands the page draws ------------------------
    risks = stockout_risks(db, company_id, limit=1000)
    if warehouse_id:
        risks = [r for r in risks if r.warehouse_id == str(warehouse_id)]

    bands = []
    for index, (key, label, lower, upper) in enumerate(RISK_BANDS):
        count = sum(
            1
            for r in risks
            # The first band is closed at the bottom. An exclusive `lower <`
            # dropped every line sitting at exactly zero days -- which is to say
            # everything already OUT of stock fell into no band at all, and the
            # most urgent column on the page read zero while two shelves were
            # empty.
            if r.days_remaining is not None
            and (r.days_remaining >= lower if index == 0 else r.days_remaining > lower)
            and r.days_remaining <= upper
        )
        bands.append({"key": key, "label": label, "count": count})
    at_risk = sum(b["count"] for b in bands if b["key"] != "low")

    # ---- Inventory health, by value ----------------------------------------
    # Three buckets that add up to the whole: stock nobody is buying, stock
    # with more cover than anyone needs, and stock doing its job.
    dead_keys = {(str(r.product_id), str(r.warehouse_id)) for r in dead_lines}
    excess_value = 0.0
    for risk in risks:
        key = (risk.product_id, risk.warehouse_id)
        if key in dead_keys:
            continue
        if risk.days_remaining is not None and risk.days_remaining > EXCESS_COVER_DAYS:
            line = next(
                (
                    r
                    for r in stock
                    if str(r.product_id) == risk.product_id
                    and str(r.warehouse_id) == risk.warehouse_id
                ),
                None,
            )
            if line:
                excess_value += float(line.unit_cost or 0) * line.quantity
    healthy_value = max(inventory_value - dead_value - excess_value, 0)

    # ---- Per-warehouse performance ----------------------------------------
    revenue_by_wh = dict(
        db.query(
            Sale.source_warehouse_id,
            func.coalesce(func.sum(Sale.total_amount), 0),
        )
        .filter(Sale.company_id == company_id, Sale.created_at >= window_start)
        .group_by(Sale.source_warehouse_id)
        .all()
    )
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

    warehouses = db.query(Warehouse).filter(Warehouse.company_id == company_id).all()
    performance = []
    for wh in warehouses:
        if warehouse_id and wh.id != warehouse_id:
            continue
        lines = [r for r in stock if r.warehouse_id == wh.id]
        out = sum(1 for r in lines if r.quantity <= 0)
        low = sum(
            1
            for r in lines
            if r.reorder_point > 0 and 0 < r.quantity <= r.reorder_point
        )
        alerts = int(alerts_by_wh.get(wh.id, 0))
        performance.append(
            {
                "id": str(wh.id),
                "name": wh.name,
                "revenue": float(revenue_by_wh.get(wh.id, 0)),
                "inventory_value": sum(
                    float(r.unit_cost or 0) * r.quantity for r in lines
                ),
                "stock_lines": len(lines),
                "stockouts": out,
                "below_reorder": low,
                "open_alerts": alerts,
                **_health(len(lines), out, low, alerts),
            }
        )
    performance.sort(key=lambda p: p["revenue"], reverse=True)

    # ---- Trading, and the trend ---------------------------------------------
    series, trend_source = _trading_series(db, company_id, days, warehouse_id)
    # The window before this one, taken as the first half of a double-length
    # series so both halves are measured the same way.
    doubled, _ = _trading_series(db, company_id, days * 2, warehouse_id)
    prior = doubled[: max(len(series), 1)]
    revenue = sum(d["revenue"] for d in series)
    prior_revenue = sum(d["revenue"] for d in prior)

    # ---- Active purchase orders --------------------------------------------
    po_q = db.query(PurchaseOrder).filter(
        PurchaseOrder.company_id == company_id,
        PurchaseOrder.status.notin_(["delivered", "cancelled"]),
    )
    if warehouse_id:
        po_q = po_q.filter(PurchaseOrder.destination_warehouse_id == warehouse_id)
    active_pos = po_q.all()
    delayed = sum(
        1
        for po in active_pos
        if po.expected_delivery_date and po.expected_delivery_date < now.date()
    )

    # ---- What needs attention ----------------------------------------------
    alert_q = (
        db.query(Alert)
        .filter(Alert.company_id == company_id, Alert.status == STATUS_OPEN)
        .order_by(
            case(
                {"critical": 0, "warning": 1, "info": 2}, value=Alert.severity, else_=3
            ),
            Alert.created_at.desc(),
        )
        .limit(6)
    )

    return {
        "range_days": days,
        "warehouse_id": str(warehouse_id) if warehouse_id else None,
        "assumptions": {
            "dead_stock_days": DEAD_STOCK_DAYS,
            "excess_cover_days": EXCESS_COVER_DAYS,
            "turnover_note": (
                "Annualised cost of goods sold over inventory held now. Proper "
                "turnover uses average inventory across the period; no "
                "historical stock snapshots are kept, so current value stands in."
            ),
            "trend_note": (
                "Unfiltered figures come from the daily projection the event "
                "consumers maintain. Filtering by site queries the sales "
                "directly, because that projection has no warehouse dimension."
            ),
            "health_formula": (
                "100 − 60×(out of stock ÷ lines) − 25×(below reorder ÷ lines) "
                "− 15×(open alerts, capped at 5)"
            ),
        },
        "kpis": {
            "revenue": round(revenue, 2),
            "revenue_change_pct": (
                ((revenue - prior_revenue) / prior_revenue * 100)
                if prior_revenue > 0
                else None
            ),
            "inventory_value": round(inventory_value, 2),
            "stock_lines": len(stock),
            "at_risk": at_risk,
            "critical": bands[0]["count"],
            "dead_value": round(dead_value, 2),
            "dead_lines": len(dead_lines),
            "turnover": turnover,
            "active_pos": len(active_pos),
            "delayed_pos": delayed,
        },
        "trend_source": trend_source,
        "revenue_trend": [
            {"date": d["date"], "revenue": d["revenue"], "orders": d["orders"]}
            for d in series
        ],
        "warehouse_performance": performance,
        "risk_bands": bands,
        "inventory_health": {
            "healthy": round(healthy_value, 2),
            "excess": round(excess_value, 2),
            "dead": round(dead_value, 2),
            "total": round(inventory_value, 2),
        },
        "critical_alerts": [
            {
                "id": str(a.id),
                "severity": a.severity,
                "title": a.title,
                "detail": a.detail,
                "raised_at": a.created_at,
            }
            for a in alert_q.all()
        ],
    }
