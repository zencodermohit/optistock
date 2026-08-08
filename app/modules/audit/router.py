from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import RequireRole
from app.modules.audit.schemas import AuditLogResponse
from app.modules.audit.models import AuditLog

router = APIRouter(prefix="/api/v1/audit", tags=["Audit Logs"])


@router.get("/", response_model=list[AuditLogResponse])
def get_audit_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    entity_name: Optional[str] = Query(None, description="Filter by entity name"),
    action: Optional[str] = Query(None, description="Filter by action"),
    db: Session = Depends(get_db),
    # Only admins can view audit logs
    current_user: dict = Depends(RequireRole(["admin"])),
):
    """
    Get a list of audit logs for compliance tracking.
    """
    # Scoped on the audit row's own company_id. The previous INNER JOIN onto
    # users meant that deleting a user (user_id is ON DELETE SET NULL) silently
    # hid every action they had ever taken.
    query = db.query(AuditLog).filter(AuditLog.company_id == current_user["company_id"])

    if entity_name:
        query = query.filter(AuditLog.entity_name == entity_name)
    if action:
        query = query.filter(AuditLog.action == action)

    return query.order_by(AuditLog.timestamp.desc()).offset(skip).limit(limit).all()
