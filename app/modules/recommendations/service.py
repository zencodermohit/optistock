from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Tuple, Optional

from app.modules.recommendations.models import Recommendation
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.modules.recommendations.schemas import RecommendationCreate


class RecommendationService:
    def __init__(self, db: Session):
        self.db = db

    def get_recommendations(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        product_id: Optional[UUID] = None,
        warehouse_id: Optional[UUID] = None,
        suggested_action: Optional[str] = None,
    ) -> Tuple[List[Recommendation], int]:
        """
        Fetch recommendations with dynamic filtering.
        Users can filter by product, warehouse, action type, or any combination.
        """
        query = (
            self.db.query(Recommendation)
            .join(Product, Recommendation.product_id == Product.id)
            .join(Warehouse, Recommendation.warehouse_id == Warehouse.id)
            .filter(
                Product.company_id == company_id, Warehouse.company_id == company_id
            )
        )

        # Dynamic Query Builder: only apply filters that were provided
        if product_id:
            query = query.filter(Recommendation.product_id == product_id)
        if warehouse_id:
            query = query.filter(Recommendation.warehouse_id == warehouse_id)
        if suggested_action:
            query = query.filter(Recommendation.suggested_action == suggested_action)

        # Order by most confident first — managers want to see the best suggestions at the top
        query = query.order_by(Recommendation.confidence_score.desc())

        total = query.count()
        recommendations = query.offset(skip).limit(limit).all()
        return recommendations, total

    def get_recommendation_by_id(
        self, rec_id: UUID, company_id: UUID
    ) -> Recommendation:
        """Fetch a single recommendation."""
        from app.core.exceptions import ResourceNotFoundError

        rec = (
            self.db.query(Recommendation)
            .join(Product, Recommendation.product_id == Product.id)
            .join(Warehouse, Recommendation.warehouse_id == Warehouse.id)
            .filter(
                Recommendation.id == rec_id,
                Product.company_id == company_id,
                Warehouse.company_id == company_id,
            )
            .first()
        )
        if not rec:
            raise ResourceNotFoundError("Recommendation", str(rec_id))
        return rec

    def create_recommendation(
        self, rec_in: RecommendationCreate, company_id: UUID
    ) -> Recommendation:
        """
        Create a new recommendation.
        In production, this would be called by an ML pipeline (e.g., Airflow task),
        not by a human user.
        """
        product = (
            self.db.query(Product)
            .filter(Product.id == rec_in.product_id, Product.company_id == company_id)
            .first()
        )
        warehouse = (
            self.db.query(Warehouse)
            .filter(
                Warehouse.id == rec_in.warehouse_id, Warehouse.company_id == company_id
            )
            .first()
        )
        if not product or not warehouse:
            from app.core.exceptions import OptiStockException

            raise OptiStockException(
                code="INVALID_TENANT_REFERENCE",
                message="Product and warehouse must belong to the active company.",
            )

        recommendation = Recommendation(
            product_id=rec_in.product_id,
            warehouse_id=rec_in.warehouse_id,
            suggested_action=rec_in.suggested_action,
            suggested_quantity=rec_in.suggested_quantity,
            confidence_score=rec_in.confidence_score,
            evidence=rec_in.evidence,
            business_reasoning=rec_in.business_reasoning,
        )
        self.db.add(recommendation)
        self.db.flush()
        return recommendation
