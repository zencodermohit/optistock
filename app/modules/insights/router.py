from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.analytics.accuracy import accuracy_summary
from app.modules.insights.service import InsightsService

router = APIRouter(prefix="/api/v1/insights", tags=["Insights"])


@router.get("/recommendations")
def list_recommendations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    action: Optional[str] = Query(None, description="reorder, transfer, discount"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Reorder suggestions, each with the arithmetic that produced it.

    Distinct from /recommendations, which is the raw record. This is the read
    model for the Insights screen: names joined in, current stock attached, and
    a cost for acting on it.
    """
    service = InsightsService(db)
    items, total = service.recommendations(
        company_id=UUID(current_user["company_id"]),
        skip=skip,
        limit=limit,
        action=action,
    )
    return {"total": total, "skip": skip, "limit": limit, "data": items}


@router.get("/accuracy")
def forecast_accuracy(
    lookback_days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """How well the forecasts have actually done.

    Published rather than kept internal, and allowed to be unflattering. A
    forecasting feature that cannot state its own error rate is asking to be
    trusted on the strength of having been built.
    """
    company_id = UUID(current_user["company_id"])
    service = InsightsService(db)

    return {
        "summary": accuracy_summary(db, company_id, lookback_days=lookback_days),
        "lookback_days": lookback_days,
        "worst": service.accuracy_detail(company_id, limit=15),
    }
