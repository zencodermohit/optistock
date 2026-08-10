"""When each stock line runs out, and why we think so.

The rest of the system answers "what is low?" -- a comparison against a reorder
point somebody typed in once. This answers the question people actually have,
which is "what runs out first, and how long have I got?".

The difference matters because a reorder point is a static number and demand is
not. Two hundred units of something selling forty a day is an emergency; two
hundred units of something selling one a day is fine, and a threshold set at
fifty flags the second and misses the first. Ranking by days remaining rather
than by units remaining reorders the list into the order a person would
actually work it.

The arithmetic is deliberately simple:

    velocity        units sold in the window / the WHOLE window
    days_left       on hand / velocity
    cover_gap       days until it drops through its reorder point

Divided by the whole window and not by the days that had sales -- the same trap
the demand forecast fell into and had to be corrected for. Ten units sold on
one day of thirty is 0.33/day, not 10/day, and the difference between those is
the difference between a calm week and a panic.

Every row carries the numbers it was computed from. That is not decoration: a
prediction a person cannot check is a prediction they will either over-trust or
ignore, and both are worse than a number with its working shown. The four
fields the UI and the assistant both lead with -- on hand, reorder point,
daily usage, days remaining -- are the four a stock controller would ask for
before believing any of it.
"""

import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.modules.analytics.eoq import calculate_eoq, calculate_safety_stock
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.sales.models import Sale, SaleItem
from app.modules.warehouses.models import Warehouse

logger = logging.getLogger(__name__)

#: Trailing window for the velocity estimate. Thirty days is long enough to
#: absorb a quiet week and short enough that a genuine change in demand is
#: visible within a month.
DEFAULT_LOOKBACK_DAYS = 30

#: Beyond this, "days remaining" stops being a useful number and starts being
#: arithmetic. Something with 4,000 days of cover is not at risk; it is
#: overstocked, which is a different report.
HORIZON_CAP_DAYS = 365

#: Risk bands, in days remaining. Chosen against ordinary lead times rather
#: than round numbers: under a week is inside almost any supplier's turnaround,
#: so it is already too late to fix by ordering normally.
CRITICAL_DAYS = 7
WARNING_DAYS = 21


@dataclass
class StockoutRisk:
    """One stock line, with its prediction and the evidence for it."""

    product_id: str
    warehouse_id: str
    sku: str
    product_name: str
    warehouse_name: str

    # -- the four numbers a person checks before believing the fifth ---------
    on_hand: int
    reorder_point: int
    daily_usage: float
    days_remaining: Optional[float]

    # -- the prediction ------------------------------------------------------
    stockout_date: Optional[str]
    days_to_reorder_point: Optional[float]
    severity: str  # critical | warning | watch | ok | idle
    #: Units sold in the window, and on how many distinct days. Two products
    #: with the same velocity are not equally predictable, and this is how a
    #: reader tells a steady seller from one that shipped a single big order.
    units_sold: int
    active_days: int
    confidence: str  # high | medium | low
    lookback_days: int
    explanation: str

    # -- what to do about it -------------------------------------------------
    #: Economic order quantity: the order size where ordering cost and holding
    #: cost balance. None when there is no demand to optimise against.
    order_quantity: Optional[int] = None
    #: Buffer covering demand variability across the lead time.
    safety_stock: Optional[int] = None
    #: The level at which ordering `order_quantity` arrives just in time.
    suggested_reorder_point: Optional[int] = None
    #: The busiest single day observed, which is what safety stock is sized on.
    peak_daily_usage: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _severity(days_remaining: Optional[float], on_hand: int, reorder: int) -> str:
    if on_hand <= 0:
        return "critical"
    if days_remaining is None:
        # Nothing sold in the window. Not safe, just unmeasured -- and saying
        # "idle" rather than "ok" keeps that distinction visible instead of
        # quietly promoting an unknown into a reassurance.
        return "idle" if on_hand > reorder else "warning"
    if days_remaining <= CRITICAL_DAYS:
        return "critical"
    if days_remaining <= WARNING_DAYS:
        return "warning"
    if days_remaining <= 60:
        return "watch"
    return "ok"


def _confidence(active_days: int, lookback_days: int) -> str:
    """How much of the window actually had sales.

    A velocity from two days of data is arithmetic, not evidence. Reported as a
    word rather than a percentage because the precision would be false -- this
    is a statement about how much we know, and three levels is all the sample
    supports.
    """
    coverage = active_days / lookback_days if lookback_days else 0
    if coverage >= 0.5:
        return "high"
    if coverage >= 0.15:
        return "medium"
    return "low"


def _reorder_policy(
    daily_usage: float, peak_daily: float, unit_cost: float
) -> Dict[str, Optional[int]]:
    """What to order, and when — from the textbook formulas and real demand.

    `calculate_eoq` and `calculate_safety_stock` have been in the codebase,
    unit-tested and uncalled, since the analytics module was written. Nothing
    was wrong with them; they needed three numbers the schema does not hold, and
    inventing those numbers quietly would have been worse than leaving the
    functions unused. They are settings now, stated on screen beside the answers
    they produce.

    One honest simplification. The safety stock formula wants demand
    variability AND lead-time variability, and this system measures the first
    but not the second: sales are recorded per day, so the busiest day observed
    is a real number, while no purchase order records when it was actually
    promised versus when it landed. So lead time is passed as its own average
    for both arguments, which reduces the formula to demand variability alone:

        safety stock = (peak daily - average daily) x lead time

    That under-covers a supplier who is late as well as busy. Saying so is
    better than a figure that looks like it accounts for something it does not.
    """
    if daily_usage <= 0 or unit_cost <= 0:
        return {
            "order_quantity": None,
            "safety_stock": None,
            "suggested_reorder_point": None,
        }

    lead_time = max(settings.SUPPLIER_LEAD_TIME_DAYS, 1)
    holding_cost = unit_cost * settings.HOLDING_COST_RATE

    try:
        eoq = calculate_eoq(
            annual_demand=daily_usage * 365,
            order_cost=settings.ORDER_COST,
            holding_cost_per_unit=holding_cost,
        )
    except ValueError:
        # The helper refuses nonsense inputs rather than returning one. A
        # product priced at zero lands here, and no recommendation is the right
        # answer for it.
        return {
            "order_quantity": None,
            "safety_stock": None,
            "suggested_reorder_point": None,
        }

    safety = calculate_safety_stock(
        max_daily_demand=max(peak_daily, daily_usage),
        max_lead_time_days=lead_time,
        avg_daily_demand=daily_usage,
        avg_lead_time_days=lead_time,
    )
    # Reorder point: cover the lead time at the usual rate, plus the buffer for
    # the days that are busier than usual.
    reorder_point = daily_usage * lead_time + safety

    return {
        "order_quantity": max(1, round(eoq)),
        "safety_stock": round(safety),
        "suggested_reorder_point": max(1, round(reorder_point)),
    }


def _explain(row: StockoutRisk) -> str:
    """One sentence a person can check, in the order they would check it.

    Written here rather than in the UI or the prompt so the screen, the API and
    the assistant cannot disagree about what a row means -- and so the model
    reads an explanation it did not have to invent.
    """
    if row.on_hand <= 0:
        return f"Out of stock at {row.warehouse_name}."
    if row.daily_usage <= 0:
        return (
            f"{row.on_hand:,} on hand at {row.warehouse_name}, with nothing sold "
            f"in {row.lookback_days} days -- no usage to project from."
        )

    when = (
        f" (around {row.stockout_date})"
        if row.stockout_date and row.days_remaining and row.days_remaining < 120
        else ""
    )
    sentence = (
        f"{row.on_hand:,} on hand at {row.warehouse_name}, selling "
        f"{row.daily_usage:.1f}/day ({row.units_sold:,} units over "
        f"{row.lookback_days} days) -- about {row.days_remaining:.0f} days "
        f"left{when}."
    )
    if row.reorder_point > 0 and row.days_to_reorder_point is not None:
        if row.days_to_reorder_point <= 0:
            sentence += f" Already below its reorder point of {row.reorder_point:,}."
        else:
            sentence += (
                f" Hits its reorder point of {row.reorder_point:,} in about "
                f"{row.days_to_reorder_point:.0f} days."
            )
    return sentence


def stockout_risks(
    db: Session,
    company_id: UUID,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    limit: int = 50,
    as_of: Optional[datetime] = None,
) -> List[StockoutRisk]:
    """Every stock line this company holds, soonest to run out first.

    One query for stock and one for sales, joined in Python. The alternative --
    a correlated subquery per line -- is tidier to read and turns into N+1 the
    moment the catalogue grows.
    """
    now = as_of or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=lookback_days)

    # Tenancy comes through the warehouse join: an inventory row carries no
    # company_id of its own, so the join IS the check.
    lines = (
        db.query(
            Inventory.product_id,
            Inventory.warehouse_id,
            Inventory.quantity,
            Inventory.reorder_point,
            Product.sku,
            Product.name.label("product_name"),
            Product.unit_cost,
            Warehouse.name.label("warehouse_name"),
        )
        .join(Product, Product.id == Inventory.product_id)
        .join(Warehouse, Warehouse.id == Inventory.warehouse_id)
        .filter(Warehouse.company_id == company_id, Product.company_id == company_id)
        .all()
    )
    if not lines:
        return []

    # Sales per (product, warehouse), because velocity is a property of a
    # location. A product selling fast in one warehouse and sitting still in
    # another has two different answers, and averaging them describes neither.
    sold = (
        db.query(
            SaleItem.product_id,
            Sale.source_warehouse_id,
            func.sum(SaleItem.quantity).label("units"),
            func.count(func.distinct(func.date(Sale.created_at))).label("days"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(
            Sale.company_id == company_id,
            Sale.created_at >= cutoff,
            # Both bounds. Without the upper one an `as_of` in the past sums
            # more days than it divides by -- the bug that inflated the demand
            # forecast's velocity by nearly three times.
            Sale.created_at < now,
        )
        .group_by(SaleItem.product_id, Sale.source_warehouse_id)
        .all()
    )
    history = {
        (str(row.product_id), str(row.source_warehouse_id)): (
            int(row.units or 0),
            int(row.days or 0),
        )
        for row in sold
    }

    # The busiest single day per line, in two stages: sum each day, then take
    # the largest. Safety stock is sized on the gap between a normal day and a
    # bad one, so an average cannot produce it -- this is the one figure in the
    # policy that has to come from daily grain.
    per_day = (
        db.query(
            SaleItem.product_id.label("product_id"),
            Sale.source_warehouse_id.label("warehouse_id"),
            func.date(Sale.created_at).label("day"),
            func.sum(SaleItem.quantity).label("units"),
        )
        .join(Sale, Sale.id == SaleItem.sale_id)
        .filter(
            Sale.company_id == company_id,
            Sale.created_at >= cutoff,
            Sale.created_at < now,
        )
        .group_by(SaleItem.product_id, Sale.source_warehouse_id, func.date(Sale.created_at))
        .subquery()
    )
    peaks = {
        (str(row.product_id), str(row.warehouse_id)): float(row.peak or 0)
        for row in db.query(
            per_day.c.product_id,
            per_day.c.warehouse_id,
            func.max(per_day.c.units).label("peak"),
        )
        .group_by(per_day.c.product_id, per_day.c.warehouse_id)
        .all()
    }

    results: List[StockoutRisk] = []
    for line in lines:
        key = (str(line.product_id), str(line.warehouse_id))
        units_sold, active_days = history.get(key, (0, 0))
        on_hand = int(line.quantity or 0)
        reorder_point = int(line.reorder_point or 0)

        daily_usage = round(units_sold / lookback_days, 3) if lookback_days else 0.0

        if daily_usage > 0 and on_hand > 0:
            days_remaining = min(on_hand / daily_usage, HORIZON_CAP_DAYS)
            stockout_date = (now + timedelta(days=days_remaining)).date().isoformat()
            days_to_reorder = max((on_hand - reorder_point) / daily_usage, 0.0)
        elif on_hand <= 0:
            days_remaining, stockout_date, days_to_reorder = 0.0, _today(now), 0.0
        else:
            days_remaining = stockout_date = days_to_reorder = None

        risk = StockoutRisk(
            product_id=str(line.product_id),
            warehouse_id=str(line.warehouse_id),
            sku=line.sku,
            product_name=line.product_name,
            warehouse_name=line.warehouse_name,
            on_hand=on_hand,
            reorder_point=reorder_point,
            daily_usage=daily_usage,
            days_remaining=(
                round(days_remaining, 1) if days_remaining is not None else None
            ),
            stockout_date=stockout_date,
            days_to_reorder_point=(
                round(days_to_reorder, 1) if days_to_reorder is not None else None
            ),
            severity=_severity(days_remaining, on_hand, reorder_point),
            units_sold=units_sold,
            active_days=active_days,
            confidence=_confidence(active_days, lookback_days),
            lookback_days=lookback_days,
            explanation="",
            peak_daily_usage=round(peaks.get(key, daily_usage), 2),
            **_reorder_policy(
                daily_usage=daily_usage,
                peak_daily=peaks.get(key, daily_usage),
                unit_cost=float(line.unit_cost or 0),
            ),
        )
        risk.explanation = _explain(risk)
        results.append(risk)

    # Soonest first; lines with no measurable usage sort last rather than
    # first, because "unknown" is not "urgent" and putting them at the top
    # would bury the rows that need action under the rows that need data.
    results.sort(
        key=lambda r: (
            r.days_remaining if r.days_remaining is not None else float("inf"),
            -r.on_hand,
        )
    )
    return results[:limit]


def summarise(risks: List[StockoutRisk]) -> Dict[str, Any]:
    """Counts by band, for a header that says how bad it is at a glance."""
    counts = {"critical": 0, "warning": 0, "watch": 0, "ok": 0, "idle": 0}
    for risk in risks:
        counts[risk.severity] = counts.get(risk.severity, 0) + 1

    soonest = next(
        (r for r in risks if r.days_remaining is not None and r.on_hand > 0), None
    )
    return {
        "counts": counts,
        "at_risk": counts["critical"] + counts["warning"],
        "soonest": (
            {
                "sku": soonest.sku,
                "days_remaining": soonest.days_remaining,
                "warehouse_name": soonest.warehouse_name,
            }
            if soonest
            else None
        ),
    }


def _today(now: datetime) -> str:
    return (now.date() if isinstance(now, datetime) else date.today()).isoformat()
