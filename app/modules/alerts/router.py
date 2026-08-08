from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import RequireRole, get_current_user
from app.core.exceptions import OptiStockException, ResourceNotFoundError
from app.modules.alerts.schemas import AlertResponse, PaginatedAlertResponse
from app.modules.alerts.service import AlertService

router = APIRouter(prefix="/api/v1/alerts", tags=["Alerts"])


@router.get("/", response_model=PaginatedAlertResponse)
def list_alerts(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query("open", description="open, resolved or dismissed"),
    severity: Optional[str] = Query(None, description="info, warning or critical"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Alerts raised by the consumers, newest first.

    Defaults to open. An alerts page whose default view includes everything ever
    resolved is a log, and the question being asked here is "what needs
    attention now".
    """
    service = AlertService(db)
    company_id = UUID(current_user["company_id"])

    alerts, total = service.list_alerts(
        company_id=company_id,
        skip=skip,
        limit=limit,
        # An explicit "all" is how a caller opts out of the default filter;
        # passing status=None would be indistinguishable from omitting it.
        status=None if status == "all" else status,
        severity=severity,
    )
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "data": alerts,
        "open_counts": service.counts_by_severity(company_id),
    }


@router.post("/{alert_id}/dismiss", response_model=AlertResponse)
def dismiss_alert(
    alert_id: UUID,
    db: Session = Depends(get_db),
    # Managers and admins only. Dismissing is a judgement that something does
    # not need acting on, which is not the same authority as seeing it.
    current_user: dict = Depends(RequireRole(["admin", "manager"])),
):
    """Wave an alert away, recorded against the person who did it."""
    service = AlertService(db)
    try:
        alert = service.dismiss(
            alert_id=alert_id,
            company_id=UUID(current_user["company_id"]),
            user_id=UUID(current_user["id"]),
        )
        db.commit()
        db.refresh(alert)
        return alert
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
