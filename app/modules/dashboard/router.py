from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.dashboard.service import DashboardService

from app.modules.analytics.dashboard import analytics

router = APIRouter(prefix="/api/v1/dashboard", tags=["Dashboard"])


@router.get("/overview")
def overview(
    days: int = Query(30, ge=7, le=90, description="Trading window in days"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Everything the front page needs, in one request.

    One endpoint rather than five, because the page is a single coherent view
    and five requests would let it render five times with the numbers
    disagreeing in between.
    """
    service = DashboardService(db)
    company_id = UUID(current_user["company_id"])

    data = service.overview(company_id, days=days)
    data["projection"] = service.projection_freshness(company_id)
    return data


@router.get("/analytics")
def analytics_dashboard(
    days: int = Query(30, ge=7, le=180),
    warehouse_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Everything the Analytics screen shows, in one request.

    One read model rather than eight endpoints: the page asks a single question
    and answering it with eight round trips would mean eight loading states
    resolving at eight different moments.
    """
    return analytics(
        db,
        company_id=UUID(current_user["company_id"]),
        days=days,
        warehouse_id=warehouse_id,
    )
