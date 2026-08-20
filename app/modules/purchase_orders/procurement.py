"""The procurement screen, in one request.

Purchase Orders used to be a table of purchase orders, which answers "what did
we order" and nothing else. The question somebody opening this page actually has
is "what should I order next, and what is going wrong with what I already
ordered" -- so the page leads with recommendations and exceptions, and the list
of orders is underneath.

Three rules this file follows.

Nothing is invented. Every figure traces to a row: recommendations come from the
forecast pipeline that already writes them, lead times are MEASURED from the
dates on past orders rather than read from a column nobody fills in, and an
order is late because its promised date has passed.

Nothing is called AI that is not. The recommendations carry a confidence score,
and that score is a data-density heuristic -- the share of days in the window
that had sales -- not a model probability. The page says so, because a number
labelled "92% confident" that means something else is worse than no number.

Revenue at risk is a ceiling, not a prediction. It is what the forecast demand
would have earned at the current selling price, which assumes every unit would
have sold. Real businesses recover some of it through substitution or a late
delivery. Labelled as exposure rather than loss.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from uuid import UUID

from sqlalchemy import Date, case, cast, func
from sqlalchemy.orm import Session

from app.modules.recommendations.models import Recommendation
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.purchase_orders.models import POItem, PurchaseOrder
from app.modules.suppliers.models import Supplier
from app.modules.warehouses.models import Warehouse

#: The four states the service writes. Draft is shown as "awaiting approval"
#: because that is what an unsent order is waiting for, but the stored value is
#: never renamed -- the page adapts to the data, not the other way round.
OPEN_STATUSES = ("draft", "submitted")

#: How far back "vs last month" compares. Thirty days against the thirty before
#: it, so the comparison is like-for-like rather than a calendar month against a
#: partial one.
TREND_DAYS = 30

#: An order this far past its promised date is critical rather than merely late.
CRITICAL_DELAY_DAYS = 3

#: A draft older than this was raised and forgotten. Somebody built a basket and
#: never sent it, which is a procurement failure that no status field records.
STALE_DRAFT_DAYS = 5


def _sparkline(db: Session, company_id: UUID, statuses, weeks: int = 8) -> List[float]:
    """Weekly order value for the last few weeks, oldest first.

    Weeks rather than days: a purchase order is a weekly-rhythm object, and a
    daily line for a business raising forty-five orders a month is mostly zeros
    with occasional spikes -- a shape that says nothing about the trend.
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(weeks=weeks)

    rows = dict(
        db.query(
            func.date_trunc("week", PurchaseOrder.created_at).label("w"),
            func.coalesce(func.sum(PurchaseOrder.total_amount), 0),
        )
        .filter(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.status.in_(statuses),
            PurchaseOrder.created_at >= start,
        )
        .group_by("w")
        .all()
    )
    # Filled, so a quiet week is a trough rather than a missing point that the
    # chart would close up.
    series = []
    for i in range(weeks):
        week = (start + timedelta(weeks=i)).date()
        match = next(
            (
                v
                for k, v in rows.items()
                if k.date().isocalendar()[:2] == week.isocalendar()[:2]
            ),
            0,
        )
        series.append(round(float(match), 2))
    return series


def _orders_raised_trend(db: Session, company_id: UUID) -> float | None:
    """Change in orders RAISED against the previous window of the same length.

    Deliberately not filtered by status, and deliberately only offered for the
    cards that describe a flow.

    The first version compared orders currently in a given status across two
    windows, which returned None for everything: an order raised two months ago
    is not still a draft, so the previous window always held zero of them. The
    fault was comparing a stock as though it were a flow. How many orders are
    open today is a level, and a level has no month-on-month change -- only the
    rate of raising them does.
    """
    now = datetime.now(timezone.utc)

    def raised(since, until=None):
        query = db.query(func.count(PurchaseOrder.id)).filter(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.created_at >= since,
        )
        if until is not None:
            query = query.filter(PurchaseOrder.created_at < until)
        return query.scalar() or 0

    window = timedelta(days=TREND_DAYS)
    current = raised(now - window)
    previous = raised(now - window * 2, now - window)

    if previous == 0:
        return None
    return round((current - previous) / previous, 4)


def _supplier_lead_times(db: Session, company_id: UUID) -> Dict[UUID, Dict[str, Any]]:
    """Each supplier's lead time, measured from its own delivered orders.

    There is no lead_time_days column on Supplier and this does not add one. The
    dates are already in the data -- how long a supplier takes is a fact about
    what it has done, not a field somebody typed -- so it is averaged out of the
    orders that actually arrived.

    Orders still in transit are excluded. Including them would count an order
    that has not arrived as evidence of how long arriving takes.
    """
    rows = (
        db.query(
            PurchaseOrder.supplier_id,
            # Postgres subtracts one date from another into a plain integer
            # of days, so the timestamp is cast down rather than the date cast
            # up through an epoch conversion nobody can read.
            func.avg(
                PurchaseOrder.expected_delivery_date
                - cast(PurchaseOrder.created_at, Date)
            ).label("lead"),
            func.count(PurchaseOrder.id).label("orders"),
        )
        .filter(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.status == "delivered",
            PurchaseOrder.expected_delivery_date.isnot(None),
        )
        .group_by(PurchaseOrder.supplier_id)
        .all()
    )
    return {
        row.supplier_id: {
            "days": round(float(row.lead or 0), 1),
            "observations": int(row.orders),
        }
        for row in rows
    }


def procurement(db: Session, company_id: UUID) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    today = now.date()

    # ------------------------------------------------------------------ KPIs --
    by_status = dict(
        db.query(PurchaseOrder.status, func.count(PurchaseOrder.id))
        .filter(PurchaseOrder.company_id == company_id)
        .group_by(PurchaseOrder.status)
        .all()
    )
    value_by_status = dict(
        db.query(
            PurchaseOrder.status,
            func.coalesce(func.sum(PurchaseOrder.total_amount), 0),
        )
        .filter(PurchaseOrder.company_id == company_id)
        .group_by(PurchaseOrder.status)
        .all()
    )

    delayed_rows = (
        db.query(
            PurchaseOrder.id,
            PurchaseOrder.expected_delivery_date,
            PurchaseOrder.total_amount,
            PurchaseOrder.created_at,
            Supplier.name.label("supplier"),
        )
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .filter(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.status == "submitted",
            PurchaseOrder.expected_delivery_date < today,
        )
        .order_by(PurchaseOrder.expected_delivery_date)
        .all()
    )

    # Urgent reorders: what the forecast pipeline says to buy, that nobody has
    # ordered yet. A recommendation with a purchase order already covering it is
    # not urgent, it is done.
    recommendations = (
        db.query(
            Recommendation,
            Product.id.label("product_id"),
            Product.sku,
            Product.name.label("product_name"),
            Product.category,
            Product.unit_cost,
            Product.selling_price,
            Warehouse.id.label("warehouse_id"),
            Warehouse.name.label("warehouse_name"),
        )
        .join(Product, Product.id == Recommendation.product_id)
        .join(Warehouse, Warehouse.id == Recommendation.warehouse_id)
        .filter(
            Product.company_id == company_id,
            Recommendation.suggested_action == "reorder",
        )
        .order_by(Recommendation.confidence_score.desc())
        .all()
    )

    # A recommendation is not urgent once an open order already covers the same
    # product at the same warehouse -- it is done, just not delivered yet.
    # Without this, the comment above promised something the query never did.
    already_ordered = {
        (row.product_id, row.warehouse_id)
        for row in (
            db.query(
                POItem.product_id,
                PurchaseOrder.destination_warehouse_id.label("warehouse_id"),
            )
            .join(PurchaseOrder, PurchaseOrder.id == POItem.po_id)
            .filter(
                PurchaseOrder.company_id == company_id,
                PurchaseOrder.status.in_(OPEN_STATUSES),
            )
            .all()
        )
    }
    recommendations = [
        row
        for row in recommendations
        if (row.product_id, row.warehouse_id) not in already_ordered
    ]

    open_count = sum(by_status.get(s, 0) for s in OPEN_STATUSES)
    open_value = sum(float(value_by_status.get(s, 0)) for s in OPEN_STATUSES)
    # Computed once and reused below in workspaces: the KPI card and the
    # workspace tile for the same statuses would otherwise run the identical
    # query twice.
    open_sparkline = _sparkline(db, company_id, OPEN_STATUSES)
    draft_sparkline = _sparkline(db, company_id, ("draft",))

    kpis = [
        {
            "key": "open",
            "label": "Open orders",
            "value": open_count,
            "amount": round(open_value, 2),
            # The only genuine flow of the four: how fast orders are being
            # raised. The other three are levels and carry no trend.
            "trend": _orders_raised_trend(db, company_id),
            "trend_label": "orders raised vs previous 30 days",
            "sparkline": open_sparkline,
            "tone": "accent",
        },
        {
            "key": "awaiting_approval",
            "label": "Awaiting approval",
            "value": by_status.get("draft", 0),
            "amount": round(float(value_by_status.get("draft", 0)), 2),
            "trend": None,
            "sparkline": draft_sparkline,
            "tone": "warning",
        },
        {
            "key": "delayed",
            "label": "Delayed orders",
            "value": len(delayed_rows),
            "amount": round(sum(float(r.total_amount or 0) for r in delayed_rows), 2),
            "trend": None,  # a stock, not a flow — a change figure would mislead
            "sparkline": [],
            "tone": "danger",
        },
        {
            "key": "urgent_reorders",
            "label": "Urgent reorders",
            "value": len(recommendations),
            "amount": round(
                sum(
                    float(r.unit_cost or 0) * (r.Recommendation.suggested_quantity or 0)
                    for r in recommendations
                ),
                2,
            ),
            "trend": None,
            "sparkline": [],
            "tone": "success",
        },
    ]

    # -------------------------------------------------------- recommendations --
    lead_times = _supplier_lead_times(db, company_id)

    # Which supplier last provided each product, and therefore who would fill
    # this order. Read from history rather than from a preferred-supplier field,
    # because there is no such field and the last supplier is the best available
    # evidence of who sells it.
    last_supplier = {}
    for row in (
        db.query(
            POItem.product_id,
            PurchaseOrder.supplier_id,
            Supplier.name,
            func.max(PurchaseOrder.created_at).label("last"),
        )
        .join(PurchaseOrder, PurchaseOrder.id == POItem.po_id)
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .filter(PurchaseOrder.company_id == company_id)
        .group_by(POItem.product_id, PurchaseOrder.supplier_id, Supplier.name)
        .order_by(func.max(PurchaseOrder.created_at).desc())
        .all()
    ):
        last_supplier.setdefault(
            row.product_id, {"id": row.supplier_id, "name": row.name}
        )

    # Keyed by (product, warehouse): a recommendation is for stock at one
    # warehouse, and summing across every warehouse the company owns would
    # mask a stockout at the warehouse that actually triggered the reorder.
    on_hand = {
        (row.product_id, row.warehouse_id): row.quantity
        for row in db.query(
            Inventory.product_id,
            Inventory.warehouse_id,
            func.coalesce(func.sum(Inventory.quantity), 0).label("quantity"),
        )
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .filter(Warehouse.company_id == company_id)
        .group_by(Inventory.product_id, Inventory.warehouse_id)
        .all()
    }

    recommended = []
    for row in recommendations:
        rec = row.Recommendation
        evidence = rec.evidence or {}
        quantity = int(rec.suggested_quantity or 0)
        supplier = last_supplier.get(row.product_id)
        lead = lead_times.get(supplier["id"]) if supplier else None

        stock = int(on_hand.get((row.product_id, row.warehouse_id), 0))
        daily = float(evidence.get("avg_daily_sales") or 0)

        recommended.append(
            {
                "id": str(rec.id),
                "product_id": str(row.product_id),
                "sku": row.sku,
                "name": row.product_name,
                "category": row.category,
                "warehouse": row.warehouse_name,
                "on_hand": stock,
                "days_of_stock": round(stock / daily, 1) if daily > 0 else None,
                "forecast_demand": int(evidence.get("forecast_quantity") or 0),
                "recommended_quantity": quantity,
                "order_value": round(float(row.unit_cost or 0) * quantity, 2),
                # A ceiling on what a stockout would cost, not a prediction.
                # It assumes every forecast unit would have sold at full price.
                "revenue_at_risk": round(float(row.selling_price or 0) * quantity, 2),
                "supplier": supplier["name"] if supplier else None,
                "lead_time_days": lead["days"] if lead else None,
                "lead_time_observations": lead["observations"] if lead else 0,
                "confidence": int(rec.confidence_score or 0),
                "reasoning": rec.business_reasoning,
                "priority": (
                    "high"
                    if stock <= 0 or (daily > 0 and stock / daily <= 7)
                    else "medium"
                ),
            }
        )

    # Most urgent first: an empty shelf outranks a confident forecast.
    recommended.sort(
        key=lambda r: (
            r["priority"] != "high",
            r["days_of_stock"] if r["days_of_stock"] is not None else 999,
            -r["confidence"],
        )
    )

    # ------------------------------------------------------------ exceptions --
    exceptions: List[Dict[str, Any]] = []

    for row in delayed_rows[:6]:
        late_by = (today - row.expected_delivery_date).days
        exceptions.append(
            {
                "key": f"delay-{row.id}",
                "kind": "supplier_delay",
                "severity": "critical" if late_by > CRITICAL_DELAY_DAYS else "high",
                "title": f"{row.supplier} is {late_by} day{'s' if late_by != 1 else ''} late",
                "detail": f"Promised {row.expected_delivery_date.isoformat()}",
                "reference": str(row.id),
                "amount": round(float(row.total_amount or 0), 2),
            }
        )

    for rec in recommended[:4]:
        if rec["priority"] != "high":
            continue
        exceptions.append(
            {
                "key": f"stockout-{rec['id']}",
                "kind": "stockout_risk",
                "severity": "critical" if rec["on_hand"] <= 0 else "high",
                "title": (
                    f"{rec['name']} is out of stock"
                    if rec["on_hand"] <= 0
                    else f"{rec['name']} has {rec['days_of_stock']:.0f} days left"
                ),
                "detail": f"{rec['on_hand']} units on hand at {rec['warehouse']}",
                "reference": rec["product_id"],
                "amount": rec["revenue_at_risk"],
            }
        )

    stale = (
        db.query(
            PurchaseOrder.id,
            PurchaseOrder.created_at,
            PurchaseOrder.total_amount,
            Supplier.name.label("supplier"),
        )
        .join(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .filter(
            PurchaseOrder.company_id == company_id,
            PurchaseOrder.status == "draft",
            PurchaseOrder.created_at < now - timedelta(days=STALE_DRAFT_DAYS),
        )
        .order_by(PurchaseOrder.created_at)
        .limit(4)
        .all()
    )
    for row in stale:
        waiting = (now - row.created_at).days
        exceptions.append(
            {
                "key": f"stale-{row.id}",
                "kind": "approval_pending",
                "severity": "medium",
                "title": f"Draft order to {row.supplier} never sent",
                "detail": f"Raised {waiting} days ago and still unapproved",
                "reference": str(row.id),
                "amount": round(float(row.total_amount or 0), 2),
            }
        )

    rank = {"critical": 0, "high": 1, "medium": 2}
    exceptions.sort(key=lambda e: (rank.get(e["severity"], 3), -e["amount"]))

    # ------------------------------------------------------------ workspaces --
    workspaces = [
        {
            "key": "open",
            "label": "Open orders",
            "statuses": list(OPEN_STATUSES),
            "count": open_count,
            "value": round(open_value, 2),
            "sparkline": open_sparkline,
        },
        {
            "key": "draft",
            "label": "Awaiting approval",
            "statuses": ["draft"],
            "count": by_status.get("draft", 0),
            "value": round(float(value_by_status.get("draft", 0)), 2),
            "sparkline": draft_sparkline,
        },
        {
            "key": "submitted",
            "label": "In transit",
            "statuses": ["submitted"],
            "count": by_status.get("submitted", 0),
            "value": round(float(value_by_status.get("submitted", 0)), 2),
            "sparkline": _sparkline(db, company_id, ("submitted",)),
        },
        {
            "key": "delivered",
            "label": "Received",
            "statuses": ["delivered"],
            "count": by_status.get("delivered", 0),
            "value": round(float(value_by_status.get("delivered", 0)), 2),
            "sparkline": _sparkline(db, company_id, ("delivered",)),
        },
        {
            "key": "cancelled",
            "label": "Cancelled",
            "statuses": ["cancelled"],
            "count": by_status.get("cancelled", 0),
            "value": round(float(value_by_status.get("cancelled", 0)), 2),
            "sparkline": _sparkline(db, company_id, ("cancelled",)),
        },
    ]

    # ------------------------------------------------------------- suppliers --
    #
    # There is deliberately no historical on-time rate here.
    #
    # The first version computed one, and it read about 1% for every supplier,
    # because it counted any delivered order whose promised date had passed as
    # late -- which is every order ever delivered. The real problem is that
    # PurchaseOrder records when an order was RAISED and when it was PROMISED,
    # and nothing at all about when it arrived. Status flips to "delivered" with
    # no timestamp.
    #
    # So on-time performance is not a hard number here; it is unmeasurable with
    # the columns that exist, and a percentage invented to fill the gap would be
    # the most quotable wrong figure on the page. What IS measurable is how many
    # of a supplier's orders are open and overdue RIGHT NOW, and how long it
    # typically says it will take. Those are reported instead.
    supplier_rows = (
        db.query(
            Supplier.id,
            Supplier.name,
            Supplier.reliability_score,
            func.count(PurchaseOrder.id).label("orders"),
            func.sum(
                case(
                    (
                        (PurchaseOrder.status == "submitted")
                        & (PurchaseOrder.expected_delivery_date < today),
                        1,
                    ),
                    else_=0,
                )
            ).label("overdue_now"),
        )
        # Outer join with the status check moved into the ON clause: a supplier
        # with no submitted/delivered order (a new one, or one whose orders are
        # all still drafts) must still appear, with orders=0, rather than
        # vanishing from the page entirely.
        .outerjoin(
            PurchaseOrder,
            (PurchaseOrder.supplier_id == Supplier.id)
            & (PurchaseOrder.status.in_(("submitted", "delivered"))),
        )
        .filter(Supplier.company_id == company_id)
        .group_by(Supplier.id, Supplier.name, Supplier.reliability_score)
        .all()
    )

    return {
        "generated_at": now.isoformat(),
        "definitions": {
            "confidence": (
                "Share of days in the forecast window that recorded a sale. A "
                "data-density heuristic, not a model probability."
            ),
            "revenue_at_risk": (
                "Forecast demand at the current selling price. A ceiling on "
                "what a stockout could cost, not a prediction of what it will."
            ),
            "lead_time": (
                "Measured from delivered orders, not stored on the supplier."
            ),
            "delayed": "Sent to the supplier and past its promised date.",
            "on_time_rate": (
                "Not reported. Purchase orders record when an order was raised "
                "and when it was promised, but not when it arrived, so "
                "historical on-time performance cannot be measured. Overdue "
                "orders open right now can."
            ),
        },
        "kpis": kpis,
        "recommendations": recommended,
        "exceptions": exceptions,
        "workspaces": workspaces,
        "suppliers": [
            {
                "id": str(row.id),
                "name": row.name,
                "orders": int(row.orders),
                "overdue_now": int(row.overdue_now or 0),
                "stated_reliability": (
                    float(row.reliability_score) if row.reliability_score else None
                ),
                "lead_time_days": lead_times.get(row.id, {}).get("days"),
            }
            for row in supplier_rows
        ],
    }
