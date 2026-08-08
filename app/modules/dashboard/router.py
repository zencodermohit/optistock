from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.modules.dashboard.service import DashboardService

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
