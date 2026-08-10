from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, RequireRole
from app.modules.users.models import User
from app.core.exceptions import OptiStockException, ResourceNotFoundError

from app.modules.transfers.schemas import (
    TransferCreate,
    TransferResponse,
    PaginatedTransfersResponse,
)
from app.modules.transfers.service import TransferService

from app.modules.analytics.readmodels import transfer_board

router = APIRouter(prefix="/api/v1/transfers", tags=["Transfers"])


def get_current_db_user(
    current_user_dict: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """Helper to get the full User ORM model from the token dict."""
    user = db.query(User).filter(User.id == current_user_dict["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/", response_model=TransferResponse, status_code=status.HTTP_201_CREATED)
def request_transfer(
    transfer_in: TransferCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
    _: dict = Depends(RequireRole(["admin", "supply_chain", "warehouse_manager"])),
):
    """Request a new stock transfer between warehouses."""
    service = TransferService(db)
    try:
        transfer = service.create_transfer(transfer_in, current_user.company_id)
        db.commit()
        return transfer
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.get("/", response_model=PaginatedTransfersResponse)
def get_transfers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(
        None, alias="status", description="e.g., pending, in_transit, completed"
    ),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List transfers."""
    service = TransferService(db)
    transfers, total = service.get_transfers(
        company_id=current_user["company_id"],
        skip=skip,
        limit=limit,
        status=status_filter,
    )

    return {"total": total, "skip": skip, "limit": limit, "data": transfers}


@router.get("/board")
def get_board(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Transfers with warehouse and product names resolved."""
    return {"data": transfer_board(db, UUID(current_user["company_id"]))}


@router.get("/{transfer_id}", response_model=TransferResponse)
def get_transfer(
    transfer_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a single transfer by ID."""
    service = TransferService(db)
    try:
        return service.get_transfer_by_id(transfer_id, current_user["company_id"])
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.patch("/{transfer_id}/ship", response_model=TransferResponse)
def ship_transfer(
    transfer_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "warehouse_manager"])),
):
    """Action: Mark as shipped. Deducts stock from source warehouse."""
    service = TransferService(db)
    try:
        transfer = service.mark_as_shipped(transfer_id, current_user["company_id"])
        db.commit()
        return transfer
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.patch("/{transfer_id}/complete", response_model=TransferResponse)
def complete_transfer(
    transfer_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "warehouse_manager"])),
):
    """Action: Mark as completed. Adds stock to destination warehouse."""
    service = TransferService(db)
    try:
        transfer = service.mark_as_completed(transfer_id, current_user["company_id"])
        db.commit()
        return transfer
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
