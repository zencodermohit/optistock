from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict
from uuid import UUID

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.modules.alerts.models import STATUS_OPEN, Alert
from app.modules.analytics.projections import recent_metrics
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse


class DashboardService:
    """Assembles the overview.

    Two kinds of number, mixed on purpose:

    *   **Trading over time** comes from the daily_metrics projection. Summing a
        year of sales on every page load gets slower every day the business
        succeeds.
    *   **Current position** -- how many lines are low, what stock is worth --
        is queried live. It is a single indexed pass over a few hundred rows,
        and projecting it would mean maintaining a second copy of a number the
        inventory table already holds exactly. Not everything should be a
        projection; the test is whether the query grows with history or only
        with the size of the catalogue.
    """

    def __init__(self, db: Session):
        self.db = db

    def overview(self, company_id: UUID, days: int = 30) -> Dict[str, Any]:
        # Twice the window is fetched, and only the recent half is returned as
        # the series. The earlier half exists solely to compare against.
        # Halving a single window instead would make the headline total cover
        # half the span the chart draws -- a big number that visibly disagrees
        # with the bars underneath it.
        full = recent_metrics(self.db, company_id, days=days * 2)
        previous, current = full[:days], full[days:]

        return {
            "range_days": days,
            "trading": self._trading_summary(previous, current),
            "series": current,
            "stock": self._stock_position(company_id),
            "alerts": self._alert_counts(company_id),
        }

    def _trading_summary(self, previous, current) -> Dict[str, Any]:
        """This period against the one before it.

        Comparing to the previous window rather than to a fixed target: "down
        12% on the previous 30 days" is actionable in a way a bare total is not.
        """

        def total(rows, key):
            return sum(row[key] for row in rows)

        revenue = total(current, "revenue")
        prior_revenue = total(previous, "revenue")

        return {
            "revenue": revenue,
            "orders": total(current, "orders"),
            "units_sold": total(current, "units_sold"),
            "movements": total(current, "stock_movements"),
            # None rather than 0 when there is no prior period: a change of
            # "0%" reads as "flat", which is a claim we cannot make.
            "revenue_change_pct": (
                ((revenue - prior_revenue) / prior_revenue * 100)
                if prior_revenue > 0
                else None
            ),
            "comparison_days": len(current),
        }

    def _stock_position(self, company_id: UUID) -> Dict[str, Any]:
        """One pass over the tenant's stock lines.

        Conditional aggregates rather than three separate COUNT queries: the
        table has to be scanned anyway, and three round trips to answer three
        questions about the same rows is three chances for them to disagree.
        """
        row = (
            self.db.query(
                func.count(Inventory.id).label("lines"),
                func.coalesce(func.sum(Inventory.quantity), 0).label("units"),
                func.coalesce(
                    func.sum(Inventory.quantity * Product.unit_cost), 0
                ).label("value"),
                func.count(
                    case(
                        (
                            (Inventory.reorder_point > 0)
                            & (Inventory.quantity <= Inventory.reorder_point)
                            & (Inventory.quantity > 0),
                            1,
                        )
                    )
                ).label("low"),
                func.count(case(((Inventory.quantity <= 0), 1))).label("out"),
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            .filter(
                Product.company_id == company_id,
                Warehouse.company_id == company_id,
            )
            .one()
        )

        return {
            "lines": row.lines or 0,
            "units": int(row.units or 0),
            # Valued at cost, not at selling price. Retail value counts profit
            # that has not been earned yet, and a stock figure that flatters
            # itself is one nobody can plan against.
            "value_at_cost": float(row.value or Decimal("0")),
            "low": row.low or 0,
            "out": row.out or 0,
        }

    def _alert_counts(self, company_id: UUID) -> Dict[str, int]:
        rows = (
            self.db.query(Alert.severity, func.count(Alert.id))
            .filter(Alert.company_id == company_id, Alert.status == STATUS_OPEN)
            .group_by(Alert.severity)
            .all()
        )
        counts = {"info": 0, "warning": 0, "critical": 0}
        for severity, total in rows:
            if severity in counts:
                counts[severity] = total
        return counts

    def projection_freshness(self, company_id: UUID) -> Dict[str, Any]:
        """When the read model was last touched.

        Surfaced rather than hidden. A projection is eventually consistent by
        construction, and a dashboard that cannot say how stale it is invites
        the reader to assume it is live.
        """
        from app.modules.analytics.projection_models import DailyMetric

        newest = (
            self.db.query(func.max(DailyMetric.updated_at))
            .filter(DailyMetric.company_id == company_id)
            .scalar()
        )
        if newest is None:
            return {"updated_at": None, "age_seconds": None}
        if newest.tzinfo is None:
            newest = newest.replace(tzinfo=timezone.utc)
        return {
            "updated_at": newest.isoformat(),
            "age_seconds": (datetime.now(timezone.utc) - newest).total_seconds(),
        }


# Kept for the router's convenience so it does not import timedelta itself.
DEFAULT_RANGE = timedelta(days=30)
