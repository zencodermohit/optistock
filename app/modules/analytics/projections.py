"""Maintaining the daily metrics read model.

Two paths into the same table, and it matters that they agree:

*   ``apply_*`` is called by a consumer for each event, keeping today current.
*   ``rebuild_daily_metrics`` recomputes a date range from the source tables.

The rebuild is what makes the incremental path safe to get wrong. A projection
is derived state, so a bug in a handler is repaired by recomputing rather than
by hand-patching numbers nobody can verify. It is also how a year of seeded
history -- which predates the event system entirely and therefore emitted no
events -- gets into a table that is otherwise only ever written by consumers.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.analytics.projection_models import DailyMetric
from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.products.models import Product
from app.modules.sales.models import Sale, SaleItem

logger = logging.getLogger(__name__)


def _bump(db: Session, company_id: UUID, day: date, **increments) -> None:
    """Add to one day's counters, creating the row if it is the first event.

    An INSERT ... ON CONFLICT DO UPDATE, not a read-modify-write. Two consumer
    replicas processing two sales for the same company in the same instant would
    both read the same starting value and both write their own total, losing one
    of them. Letting Postgres do the addition makes the operation atomic and the
    race disappears.
    """
    columns = {name: value for name, value in increments.items() if value}
    if not columns:
        return

    statement = insert(DailyMetric).values(
        company_id=company_id,
        metric_date=day,
        **columns,
    )
    statement = statement.on_conflict_do_update(
        index_elements=["company_id", "metric_date"],
        set_={
            name: getattr(DailyMetric, name) + value for name, value in columns.items()
        }
        | {"updated_at": datetime.now(timezone.utc)},
    )
    db.execute(statement)


def apply_sale(db: Session, company_id: UUID, day: date, payload: dict) -> None:
    _bump(
        db,
        company_id,
        day,
        revenue=Decimal(str(payload.get("total_amount") or 0)),
        orders=1,
        units_sold=int(payload.get("unit_count") or 0),
    )


def apply_movement(db: Session, company_id: UUID, day: date, payload: dict) -> None:
    change = int(payload.get("quantity_change") or 0)
    _bump(
        db,
        company_id,
        day,
        stock_movements=1,
        # Only inbound counts as received. Outbound is already captured as
        # units_sold when it came from a sale, and counting it twice under a
        # second name would make the two numbers quietly contradict each other.
        units_received=change if change > 0 else 0,
    )


def rebuild_daily_metrics(
    db: Session,
    company_id: Optional[UUID] = None,
    since: Optional[date] = None,
) -> int:
    """Recompute the projection from the source tables. Returns rows written.

    Deletes the range first rather than upserting over it. An upsert would leave
    behind days that exist in the projection but no longer in the source -- for
    example after a sale is voided -- and a row that nothing can produce is a row
    nobody will ever notice is wrong.
    """
    sales_query = select(
        Sale.company_id,
        func.date(Sale.created_at).label("day"),
        func.sum(Sale.total_amount).label("revenue"),
        func.count(func.distinct(Sale.id)).label("orders"),
    ).group_by(Sale.company_id, func.date(Sale.created_at))

    units_query = (
        select(
            Sale.company_id,
            func.date(Sale.created_at).label("day"),
            func.sum(SaleItem.quantity).label("units"),
        )
        .join(SaleItem, SaleItem.sale_id == Sale.id)
        .group_by(Sale.company_id, func.date(Sale.created_at))
    )

    # Movements reach their company through the product, since the ledger only
    # knows which inventory row it touched.
    movements_query = (
        select(
            Product.company_id,
            func.date(InventoryMovement.created_at).label("day"),
            func.count(InventoryMovement.id).label("movements"),
            func.sum(func.greatest(InventoryMovement.quantity_change, 0)).label(
                "received"
            ),
        )
        .join(Inventory, InventoryMovement.inventory_id == Inventory.id)
        .join(Product, Inventory.product_id == Product.id)
        .group_by(Product.company_id, func.date(InventoryMovement.created_at))
    )

    if company_id:
        sales_query = sales_query.where(Sale.company_id == company_id)
        units_query = units_query.where(Sale.company_id == company_id)
        movements_query = movements_query.where(Product.company_id == company_id)
    if since:
        sales_query = sales_query.where(func.date(Sale.created_at) >= since)
        units_query = units_query.where(func.date(Sale.created_at) >= since)
        movements_query = movements_query.where(
            func.date(InventoryMovement.created_at) >= since
        )

    totals: dict[tuple[UUID, date], dict] = {}

    def slot(key):
        return totals.setdefault(
            key,
            {
                "revenue": Decimal("0"),
                "orders": 0,
                "units_sold": 0,
                "stock_movements": 0,
                "units_received": 0,
            },
        )

    for row in db.execute(sales_query):
        entry = slot((row.company_id, row.day))
        entry["revenue"] = row.revenue or Decimal("0")
        entry["orders"] = row.orders or 0
    for row in db.execute(units_query):
        slot((row.company_id, row.day))["units_sold"] = int(row.units or 0)
    for row in db.execute(movements_query):
        entry = slot((row.company_id, row.day))
        entry["stock_movements"] = int(row.movements or 0)
        entry["units_received"] = int(row.received or 0)

    delete = DailyMetric.__table__.delete()
    if company_id is not None:
        delete = delete.where(DailyMetric.company_id == company_id)
    if since is not None:
        delete = delete.where(DailyMetric.metric_date >= since)
    db.execute(delete)

    if totals:
        db.execute(
            DailyMetric.__table__.insert(),
            [
                {"company_id": key[0], "metric_date": key[1], **values}
                for key, values in totals.items()
            ],
        )

    db.flush()
    logger.info("Rebuilt %d daily metric rows.", len(totals))
    return len(totals)


def recent_metrics(db: Session, company_id: UUID, days: int = 30):
    """The last N days, oldest first, with missing days filled in as zero.

    Gaps matter: a chart that skips quiet days draws a straight line across them
    and reports trading that never happened.
    """
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days - 1)

    rows = {
        row.metric_date: row
        for row in db.query(DailyMetric)
        .filter(
            DailyMetric.company_id == company_id,
            DailyMetric.metric_date >= start,
            DailyMetric.metric_date <= end,
        )
        .all()
    }

    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = rows.get(day)
        series.append(
            {
                "date": day.isoformat(),
                "revenue": float(row.revenue) if row else 0.0,
                "orders": row.orders if row else 0,
                "units_sold": row.units_sold if row else 0,
                "stock_movements": row.stock_movements if row else 0,
                "units_received": row.units_received if row else 0,
            }
        )
    return series
