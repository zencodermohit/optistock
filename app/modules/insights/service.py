from typing import Any, Dict, List, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.analytics.models import ForecastRun
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.recommendations.models import Recommendation
from app.modules.warehouses.models import Warehouse


class InsightsService:
    """Recommendations and forecast accuracy, shaped for the screen that shows them."""

    def __init__(self, db: Session):
        self.db = db

    def recommendations(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        action: str | None = None,
    ) -> Tuple[List[dict], int]:
        """Recommendations with the names and current stock needed to judge them.

        Joined rather than fetched per row. A list of fifty suggestions that
        each need a product lookup, a warehouse lookup and a stock lookup is
        one hundred and fifty follow-up queries to render one page.

        Current on-hand is included because a recommendation is a claim about a
        moment that has already passed -- it was computed overnight, and stock
        has moved since. Showing what the number is now is what lets a reader
        see the suggestion has been overtaken.
        """
        query = (
            self.db.query(
                Recommendation.id,
                Recommendation.product_id,
                Recommendation.warehouse_id,
                Recommendation.suggested_action,
                Recommendation.suggested_quantity,
                Recommendation.confidence_score,
                Recommendation.evidence,
                Recommendation.business_reasoning,
                Recommendation.source,
                Recommendation.created_at,
                Product.sku,
                Product.name.label("product_name"),
                Product.abc_class,
                Product.unit_cost,
                Warehouse.name.label("warehouse_name"),
                Inventory.quantity.label("quantity_on_hand"),
            )
            .join(Product, Recommendation.product_id == Product.id)
            .join(Warehouse, Recommendation.warehouse_id == Warehouse.id)
            # Outer: a recommendation can name a pair with no stock row yet,
            # and an inner join would silently drop exactly the products that
            # have never been stocked -- the ones most worth reordering.
            .outerjoin(
                Inventory,
                (Inventory.product_id == Recommendation.product_id)
                & (Inventory.warehouse_id == Recommendation.warehouse_id),
            )
            .filter(
                Product.company_id == company_id,
                Warehouse.company_id == company_id,
            )
        )

        if action:
            query = query.filter(Recommendation.suggested_action == action)

        total = query.count()
        rows = (
            query.order_by(Recommendation.confidence_score.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

        return [self._to_recommendation(row) for row in rows], total

    @staticmethod
    def _to_recommendation(row) -> dict:
        on_hand = row.quantity_on_hand or 0
        unit_cost = float(row.unit_cost or 0)
        return {
            **{
                key: value
                for key, value in row._mapping.items()
                if key not in {"unit_cost", "quantity_on_hand"}
            },
            "quantity_on_hand": on_hand,
            # What acting on this would cost, at cost price. A suggestion to
            # order 4,000 units reads very differently once it carries a
            # dditional price tag, and that is the number a manager is actually
            # deciding about.
            "estimated_cost": round(unit_cost * row.suggested_quantity, 2),
        }

    def accuracy_detail(
        self, company_id: UUID, limit: int = 15
    ) -> List[Dict[str, Any]]:
        """Scored predictions with product names, worst miss first."""
        rows = (
            self.db.query(
                ForecastRun.id,
                ForecastRun.forecast_quantity,
                ForecastRun.actual_quantity,
                ForecastRun.absolute_error,
                ForecastRun.horizon_days,
                ForecastRun.horizon_end,
                ForecastRun.confidence_score,
                Product.sku,
                Product.name.label("product_name"),
                Warehouse.name.label("warehouse_name"),
            )
            .join(Product, ForecastRun.product_id == Product.id)
            .join(Warehouse, ForecastRun.warehouse_id == Warehouse.id)
            .filter(
                ForecastRun.company_id == company_id,
                ForecastRun.scored_at.isnot(None),
            )
            .order_by(ForecastRun.absolute_error.desc())
            .limit(limit)
            .all()
        )

        detail = []
        for row in rows:
            actual = row.actual_quantity or 0
            detail.append(
                {
                    **row._mapping,
                    # Signed, so over- and under-forecasting are visibly
                    # different failures. A dashboard that only shows magnitude
                    # cannot tell you the model is biased in one direction.
                    "error": row.forecast_quantity - actual,
                    "direction": ("over" if row.forecast_quantity > actual else "under")
                    if row.forecast_quantity != actual
                    else "exact",
                }
            )
        return detail
