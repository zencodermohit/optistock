from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, RequireRole
from app.core.exceptions import OptiStockException, ResourceNotFoundError

from app.modules.recommendations.schemas import (
    RecommendationCreate,
    RecommendationResponse,
    PaginatedRecommendationsResponse,
)
from app.modules.recommendations.service import RecommendationService

router = APIRouter(prefix="/api/v1/recommendations", tags=["Recommendations"])


@router.get("/", response_model=PaginatedRecommendationsResponse)
def get_recommendations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    product_id: Optional[UUID] = Query(None, description="Filter by product"),
    warehouse_id: Optional[UUID] = Query(None, description="Filter by warehouse"),
    suggested_action: Optional[str] = Query(
        None, description="e.g., reorder, transfer, discount"
    ),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get recommendations with optional filters.
    Results are sorted by confidence_score (highest first).
    """
    service = RecommendationService(db)
    recs, total = service.get_recommendations(
        company_id=current_user["company_id"],
        skip=skip,
        limit=limit,
        product_id=product_id,
        warehouse_id=warehouse_id,
        suggested_action=suggested_action,
    )

    return {"total": total, "skip": skip, "limit": limit, "data": recs}


@router.get("/{rec_id}", response_model=RecommendationResponse)
def get_recommendation(
    rec_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a single recommendation by ID."""
    service = RecommendationService(db)
    try:
        return service.get_recommendation_by_id(rec_id, current_user["company_id"])
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.post("/", response_model=RecommendationResponse, status_code=201)
def create_recommendation(
    rec_in: RecommendationCreate,
    db: Session = Depends(get_db),
    # Only admins (or ML pipelines using an admin service account) can create recommendations
    current_user: dict = Depends(RequireRole(["admin"])),
):
    """
    Create a new recommendation.
    In production, this endpoint would be called by an ML pipeline (e.g., Airflow),
    not directly by a human user.
    """
    service = RecommendationService(db)
    try:
        rec = service.create_recommendation(rec_in, current_user["company_id"])
        db.commit()
        return rec
    # Without this the tenant-boundary rejection escaped as an unhandled
    # exception, so a cross-tenant reference returned an opaque 500 instead of a
    # 400 explaining what was wrong.
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
