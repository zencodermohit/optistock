"""Everything known about one SKU, in one request.

Layer 2 of the Products module. The hub answers "which product needs me"; this
answers "what is going on with this one, and what should I do about it" — which
previously required four screens and a mental join.

The organising idea is that a product detail page is not a form. The editable
fields are the least interesting thing about a SKU; what matters is how it has
BEHAVED — whether demand is rising, whether the stock is in the right building,
how long it has been selling, and what it sells alongside. So the record sits in
a header and the rest of the page is measurement.

Every number here is derived from sales, inventory and purchase rows. Nothing is
stored on Product except its identity and its price, and nothing is invented: a
field with no evidence behind it comes back null and the UI says so.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session, aliased

from app.modules.analytics.eoq import calculate_eoq, calculate_safety_stock
from app.modules.inventory.models import Inventory
from app.modules.products.intelligence import (
    AT_RISK_COVER_DAYS,
    DEAD_DAYS,
    OVERSTOCK_COVER_DAYS,
    _classify,
)
from app.modules.products.models import Product
from app.modules.purchase_orders.models import POItem, PurchaseOrder
from app.modules.sales.models import Sale, SaleItem
from app.modules.suppliers.models import Supplier
from app.modules.warehouses.models import Warehouse

#: Annual holding cost as a fraction of what a unit cost to buy. Warehousing,
#: insurance, capital and shrinkage. Twenty-two per cent is the usual textbook
#: figure; it is stated in the response rather than hidden, because EOQ is only
#: as good as this assumption and the reader deserves to see it.
HOLDING_COST_RATE = 0.22

#: Fixed cost of raising one purchase order, in rupees. Paperwork, inbound
#: handling, receiving. Also declared, for the same reason.
ORDER_COST = 2500.0

#: How far back the seasonality chart looks. Two years, so the same month can be
#: compared against itself -- one year of data draws a line nobody can read a
#: pattern from.
SEASONALITY_MONTHS = 24


def _health(
    bucket: str,
    cover: Optional[float],
    growth: Optional[float],
    margin: Optional[float],
    days_since_sale: Optional[int],
) -> Dict[str, Any]:
    """A health score with its workings shown.

    One number is easier to scan than six, and a number nobody can explain is
    worse than no number at all. So this returns the deductions alongside the
    score, and the page lists them -- the score is a summary of the factors, not
    a replacement for them.

    Deliberately not a weighted average of normalised sub-scores. That produces
    a number that moves for reasons nobody can name. Every product starts at 100
    and loses points for specific, nameable problems.
    """
    factors: List[Dict[str, Any]] = []

    def deduct(points: int, label: str, detail: str) -> None:
        factors.append({"label": label, "impact": -points, "detail": detail})

    if bucket == "critical":
        deduct(40, "Out of stock", "Selling steadily with nothing on any shelf.")
    elif cover is not None and cover <= AT_RISK_COVER_DAYS:
        deduct(
            22,
            "Low cover",
            f"About {cover:.0f} days left at the current rate.",
        )
    elif cover is not None and cover > OVERSTOCK_COVER_DAYS:
        deduct(
            15,
            "Overstocked",
            f"{cover:.0f} days of cover — capital sitting still.",
        )

    if days_since_sale is None:
        deduct(25, "Never sold", "No sale has ever been recorded for this SKU.")
    elif days_since_sale >= DEAD_DAYS:
        deduct(
            25,
            "Demand has stopped",
            f"Nothing sold in {days_since_sale} days.",
        )

    if growth is not None and growth <= -0.20:
        deduct(
            15,
            "Demand falling",
            f"Down {abs(growth) * 100:.0f}% on the previous period.",
        )

    if margin is not None and margin < 0.10:
        deduct(
            10,
            "Thin margin",
            f"Selling at {margin * 100:.0f}% margin.",
        )

    score = max(0, 100 + sum(f["impact"] for f in factors))

    if score >= 85:
        band = "strong"
    elif score >= 65:
        band = "fair"
    elif score >= 40:
        band = "weak"
    else:
        band = "critical"

    return {"score": score, "band": band, "factors": factors}


def product_command_center(
    db: Session, company_id: UUID, product_id: UUID, days: int = 90
) -> Optional[Dict[str, Any]]:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.company_id == company_id)
        .first()
    )
    if product is None:
        return None

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=days)
    prior_start = now - timedelta(days=days * 2)

    cost = float(product.unit_cost or 0)
    price = float(product.selling_price or 0)
    margin = ((price - cost) / price) if price > 0 else None

    # ---------------------------------------------------------------- stock --
    sites = (
        db.query(
            Warehouse.id,
            Warehouse.name,
            Warehouse.location_code,
            Inventory.quantity,
            Inventory.reorder_point,
        )
        .join(Inventory, Inventory.warehouse_id == Warehouse.id)
        .filter(
            Inventory.product_id == product_id,
            Warehouse.company_id == company_id,
        )
        .order_by(Inventory.quantity.desc())
        .all()
    )
    on_hand = sum(int(s.quantity or 0) for s in sites)

    # --------------------------------------------------------------- demand --
    def sold_between(start, end):
        row = (
            db.query(
                func.coalesce(func.sum(SaleItem.quantity), 0),
                func.coalesce(
                    func.sum(SaleItem.quantity * SaleItem.unit_price), 0
                ),
                func.count(func.distinct(Sale.id)),
            )
            .join(Sale, Sale.id == SaleItem.sale_id)
            .filter(
                SaleItem.product_id == product_id,
                Sale.company_id == company_id,
                Sale.created_at >= start,
                Sale.created_at < end,
            )
            .one()
        )
        return int(row[0]), float(row[1]), int(row[2])

    units_sold, revenue, order_count = sold_between(window_start, now)
    prior_units, prior_revenue, _ = sold_between(prior_start, window_start)

    # Divided by the whole window, not by the days that happened to have sales.
    # A product that sold 30 units in one day of a 90-day window sells a third
    # of a unit a day, not thirty.
    daily_rate = units_sold / days if days else 0.0
    cover = (on_hand / daily_rate) if daily_rate > 0 else None
    growth = (
        (units_sold - prior_units) / prior_units if prior_units > 0 else None
    )

    # Daily series for the window. Days with no sales are filled with zero here
    # rather than left out -- a line chart that skips empty days compresses time
    # and draws a busier product than the one that exists.
    daily_rows = dict(
        db.query(
            func.date(Sale.created_at),
            func.sum(SaleItem.quantity),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .filter(
            SaleItem.product_id == product_id,
            Sale.company_id == company_id,
            Sale.created_at >= window_start,
        )
        .group_by(func.date(Sale.created_at))
        .all()
    )
    series = []
    for offset in range(days):
        day = (window_start + timedelta(days=offset)).date()
        series.append({"date": day.isoformat(), "units": int(daily_rows.get(day, 0))})

    # Monthly totals, for the shape of the year rather than the noise of a day.
    #
    # Started on a month BOUNDARY rather than a fixed number of days back. Two
    # years of days lands mid-month and draws a first bar that is short because
    # it is half a month, not because demand was low -- and a reader cannot tell
    # those apart. The current month is genuinely partial and is labelled so.
    this_month = now.replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    month = this_month.month - (SEASONALITY_MONTHS - 1)
    year = this_month.year + (month - 1) // 12
    season_start = this_month.replace(year=year, month=(month - 1) % 12 + 1)
    current_month = this_month.strftime("%Y-%m")

    monthly = {
        row[0].strftime("%Y-%m"): (int(row[1] or 0), float(row[2] or 0))
        for row in db.query(
            func.date_trunc("month", Sale.created_at).label("m"),
            func.sum(SaleItem.quantity),
            func.sum(SaleItem.quantity * SaleItem.unit_price),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .filter(
            SaleItem.product_id == product_id,
            Sale.company_id == company_id,
            Sale.created_at >= season_start,
        )
        .group_by("m")
        .order_by("m")
        .all()
    }

    # Every month in the span, including the ones that sold nothing.
    #
    # The GROUP BY only returns months that HAVE sales, so a product that went
    # quiet for a quarter came back with three fewer bars -- and a bar chart
    # with months missing does not show a gap, it closes it. The silence is the
    # most important thing on the chart for a dying product, so it is drawn.
    seasonality = []
    for step in range(SEASONALITY_MONTHS):
        m = season_start.month + step
        key = season_start.replace(
            year=season_start.year + (m - 1) // 12, month=(m - 1) % 12 + 1
        ).strftime("%Y-%m")
        units, revenue = monthly.get(key, (0, 0.0))
        seasonality.append(
            {
                "month": key,
                "units": units,
                "revenue": round(revenue, 2),
                # The month in progress is not comparable with the ones that
                # finished. Flagged rather than dropped, because hiding the
                # current month makes a page look a month out of date.
                "partial": key == current_month,
            }
        )

    # ------------------------------------------------------------- lifetime --
    lifetime = (
        db.query(
            func.min(Sale.created_at),
            func.max(Sale.created_at),
            func.coalesce(func.sum(SaleItem.quantity), 0),
            func.coalesce(
                func.sum(SaleItem.quantity * SaleItem.unit_price), 0
            ),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .filter(
            SaleItem.product_id == product_id, Sale.company_id == company_id
        )
        .one()
    )
    first_sale, last_sale, lifetime_units, lifetime_revenue = lifetime
    days_since_sale = (now - last_sale).days if last_sale else None

    # Complete months only. The month in progress cannot be the best one on
    # record when it is not over, and letting it win produces a "best month"
    # that quietly changes every few days.
    complete = [m for m in seasonality if not m["partial"]]
    best_month = max(complete, key=lambda m: m["units"]) if complete else None

    bucket = _classify(on_hand, daily_rate, days_since_sale, growth)

    # --------------------------------------------------- bought alongside ----
    # Self-join on the sale: every other product that appeared on the same
    # order. Useful because a stockout on a product with strong companions
    # costs more than its own revenue -- it can lose the whole basket.
    other = aliased(SaleItem)
    together = [
        {
            "id": str(row[0]),
            "sku": row[1],
            "name": row[2],
            "category": row[3],
            "orders": int(row[4]),
            "attach_rate": round(int(row[4]) / order_count, 3)
            if order_count
            else None,
        }
        for row in db.query(
            Product.id,
            Product.sku,
            Product.name,
            Product.category,
            func.count(func.distinct(SaleItem.sale_id)).label("orders"),
        )
        .join(SaleItem, SaleItem.product_id == product_id)
        .join(other, other.sale_id == SaleItem.sale_id)
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(
            Product.id == other.product_id,
            Product.id != product_id,
            Sale.company_id == company_id,
            Sale.created_at >= window_start,
        )
        .group_by(Product.id, Product.sku, Product.name, Product.category)
        .order_by(func.count(func.distinct(SaleItem.sale_id)).desc())
        .limit(5)
        .all()
    ]

    # -------------------------------------------------------------- supply ---
    purchases = [
        {
            "id": str(row[0]),
            "supplier": row[1],
            "status": row[2],
            "quantity": int(row[3] or 0),
            "unit_price": round(float(row[4] or 0), 2),
            "created_at": row[5].isoformat() if row[5] else None,
            "expected": row[6].isoformat() if row[6] else None,
        }
        for row in db.query(
            PurchaseOrder.id,
            Supplier.name,
            PurchaseOrder.status,
            POItem.quantity,
            POItem.unit_price,
            PurchaseOrder.created_at,
            PurchaseOrder.expected_delivery_date,
        )
        .join(POItem, POItem.po_id == PurchaseOrder.id)
        .outerjoin(Supplier, Supplier.id == PurchaseOrder.supplier_id)
        .filter(
            POItem.product_id == product_id,
            PurchaseOrder.company_id == company_id,
        )
        .order_by(PurchaseOrder.created_at.desc())
        .limit(6)
        .all()
    ]

    # Planned lead time, from orders that carry a delivery date. Called planned
    # rather than actual because there is no received-at column to measure the
    # real one, and reporting a plan as an outcome is how forecasts start lying.
    lead_times = [
        (
            datetime.fromisoformat(p["expected"]).date()
            - datetime.fromisoformat(p["created_at"]).date()
        ).days
        for p in purchases
        if p["expected"] and p["created_at"]
    ]
    lead_times = [d for d in lead_times if d >= 0]
    avg_lead_time = (sum(lead_times) / len(lead_times)) if lead_times else None

    # ------------------------------------------------------ recommendation ---
    recommendation: Optional[Dict[str, Any]] = None
    if daily_rate > 0 and cost > 0:
        annual_demand = daily_rate * 365
        holding = cost * HOLDING_COST_RATE
        eoq = calculate_eoq(annual_demand, ORDER_COST, holding)

        # Peak daily demand from the observed window, not a multiplier of the
        # mean. The whole point of safety stock is to survive the busy day that
        # actually happened.
        peak_daily = max((d["units"] for d in series), default=0)
        lead = avg_lead_time if avg_lead_time is not None else 14
        safety = calculate_safety_stock(peak_daily, lead, daily_rate, lead)
        reorder_point = daily_rate * lead + safety

        recommendation = {
            "eoq": int(round(eoq)),
            "safety_stock": int(round(safety)),
            "reorder_point": int(round(reorder_point)),
            "lead_time_days": round(lead, 1),
            "lead_time_source": (
                "planned, from purchase orders"
                if avg_lead_time is not None
                else "assumed — no purchase order carries a delivery date"
            ),
            "order_now": on_hand <= reorder_point,
            "assumptions": {
                "holding_cost_rate": HOLDING_COST_RATE,
                "order_cost": ORDER_COST,
                "annual_demand": int(round(annual_demand)),
                "peak_daily_demand": peak_daily,
            },
        }

    return {
        "range_days": days,
        "product": {
            "id": str(product.id),
            "sku": product.sku,
            "name": product.name,
            "category": product.category,
            "status": product.status,
            "abc_class": product.abc_class,
            "unit_cost": cost,
            "selling_price": price,
            "margin": round(margin, 4) if margin is not None else None,
            "created_at": product.created_at.isoformat()
            if product.created_at
            else None,
        },
        "health": _health(bucket, cover, growth, margin, days_since_sale),
        "metrics": {
            "bucket": bucket,
            "on_hand": on_hand,
            "sites": len(sites),
            "inventory_value": round(cost * on_hand, 2),
            "units_sold": units_sold,
            "revenue": round(revenue, 2),
            "orders": order_count,
            "daily_rate": round(daily_rate, 3),
            "days_cover": round(cover, 1) if cover is not None else None,
            "growth": round(growth, 4) if growth is not None else None,
            "prior_units": prior_units,
            "prior_revenue": round(prior_revenue, 2),
            "days_since_sale": days_since_sale,
        },
        "series": series,
        "seasonality": seasonality,
        "warehouses": [
            {
                "id": str(s.id),
                "name": s.name,
                "location_code": s.location_code,
                "quantity": int(s.quantity or 0),
                "reorder_point": int(s.reorder_point or 0),
                "share": round(int(s.quantity or 0) / on_hand, 4)
                if on_hand > 0
                else 0.0,
                "below_reorder": (s.reorder_point or 0) > 0
                and int(s.quantity or 0) <= int(s.reorder_point or 0),
            }
            for s in sites
        ],
        "lifetime": {
            "first_sale": first_sale.isoformat() if first_sale else None,
            "last_sale": last_sale.isoformat() if last_sale else None,
            "units": int(lifetime_units or 0),
            "revenue": round(float(lifetime_revenue or 0), 2),
            "days_selling": (now - first_sale).days if first_sale else None,
            "best_month": best_month,
        },
        "bought_together": together,
        "purchases": purchases,
        "recommendation": recommendation,
    }
