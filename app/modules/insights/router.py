from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.analytics.accuracy import accuracy_summary
from app.modules.analytics.stockout import stockout_risks, summarise
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


@router.get("/stockout-risk")
def stockout_risk(
    lookback_days: int = Query(30, ge=7, le=90),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """When each stock line runs out, soonest first.

    Distinct from /inventory?low_only=true, which compares against a static
    reorder point. This ranks by days remaining at the observed sales rate, so
    two hundred units selling forty a day sorts above two hundred selling one.
    Every row carries the numbers it was computed from -- a prediction a person
    cannot check is one they will either over-trust or ignore.
    """
    risks = stockout_risks(
        db,
        UUID(current_user["company_id"]),
        lookback_days=lookback_days,
        limit=limit,
    )
    return {
        "lookback_days": lookback_days,
        "summary": summarise(risks),
        # Published with the figures they produced. An "optimal" order quantity
        # is only as meaningful as the costs it was optimised against, and a
        # reader who cannot see the assumption cannot judge the answer.
        "assumptions": {
            "lead_time_days": settings.SUPPLIER_LEAD_TIME_DAYS,
            "order_cost": settings.ORDER_COST,
            "holding_cost_rate": settings.HOLDING_COST_RATE,
        },
        "data": [r.to_dict() for r in risks],
    }
