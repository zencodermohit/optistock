from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, RequireRole
from app.modules.users.models import User
from app.core.exceptions import OptiStockException, ResourceNotFoundError

from app.modules.reconciliation.schemas import (
    ReconciliationCreate,
    ReconciliationResponse,
    PaginatedReconciliationsResponse,
)
from app.modules.reconciliation.service import ReconciliationService

router = APIRouter(prefix="/api/v1/reconciliations", tags=["Reconciliation"])


def get_current_db_user(
    current_user_dict: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    user = db.query(User).filter(User.id == current_user_dict["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post(
    "/", response_model=ReconciliationResponse, status_code=status.HTTP_201_CREATED
)
def submit_reconciliation(
    recon_in: ReconciliationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
    # Any warehouse worker/analyst can SUBMIT a count
    _: dict = Depends(RequireRole(["admin", "warehouse_manager", "analyst"])),
):
    """Submit a cycle count batch. Starts as 'pending'."""
    service = ReconciliationService(db)
    try:
        recon = service.create_reconciliation(recon_in, current_user.company_id)
        db.commit()
        return recon
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to submit reconciliation")


@router.get("/", response_model=PaginatedReconciliationsResponse)
def get_reconciliations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List reconciliations."""
    service = ReconciliationService(db)
    recons, total = service.get_reconciliations(
        company_id=current_user["company_id"],
        skip=skip,
        limit=limit,
        status=status_filter,
    )

    return {"total": total, "skip": skip, "limit": limit, "data": recons}


@router.get("/{recon_id}", response_model=ReconciliationResponse)
def get_reconciliation(
    recon_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a single reconciliation by ID."""
    service = ReconciliationService(db)
    try:
        return service.get_reconciliation_by_id(recon_id, current_user["company_id"])
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.patch("/{recon_id}/approve", response_model=ReconciliationResponse)
def approve_reconciliation(
    recon_id: UUID,
    db: Session = Depends(get_db),
    # ONLY Managers can APPROVE the count
    current_user: dict = Depends(RequireRole(["admin", "warehouse_manager"])),
):
    """Action: Approve the batch. This physically modifies the inventory ledger."""
    service = ReconciliationService(db)
    try:
        recon = service.approve_reconciliation(recon_id, current_user["company_id"])
        db.commit()
        return recon
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.patch("/{recon_id}/reject", response_model=ReconciliationResponse)
def reject_reconciliation(
    recon_id: UUID,
    db: Session = Depends(get_db),
    # ONLY Managers can REJECT the count
    current_user: dict = Depends(RequireRole(["admin", "warehouse_manager"])),
):
    """Action: Reject the batch. Tells the worker to go recount the aisle."""
    service = ReconciliationService(db)
    try:
        recon = service.reject_reconciliation(recon_id, current_user["company_id"])
        db.commit()
        return recon
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
