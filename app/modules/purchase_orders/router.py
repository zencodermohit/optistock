from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, RequireRole
from app.modules.users.models import User
from app.core.exceptions import OptiStockException, ResourceNotFoundError

from app.modules.purchase_orders.schemas import (
    PurchaseOrderCreate,
    PurchaseOrderResponse,
    PaginatedPOResponse,
)
from app.modules.purchase_orders.service import PurchaseOrderService

router = APIRouter(prefix="/api/v1/purchase_orders", tags=["Purchase Orders"])


def get_current_db_user(
    current_user_dict: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """Helper to get the full User ORM model from the token dict."""
    user = db.query(User).filter(User.id == current_user_dict["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post(
    "/", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED
)
def create_po(
    po_in: PurchaseOrderCreate,
    db: Session = Depends(get_db),
    # Get the user to attach the company_id
    current_user: User = Depends(get_current_db_user),
    # RBAC: Enforce role, but we use `_` because we don't need the return value
    _: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    """Create a new Purchase Order in 'draft' status."""
    service = PurchaseOrderService(db)
    try:
        po = service.create_po(po_in, current_user.company_id)
        db.commit()
        return po
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500, detail="An error occurred creating the PO."
        )


@router.get("/", response_model=PaginatedPOResponse)
def get_purchase_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filter by status (e.g., draft, delivered)"
    ),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a paginated list of Purchase Orders."""
    service = PurchaseOrderService(db)
    pos, total = service.get_pos(
        company_id=current_user["company_id"],
        skip=skip,
        limit=limit,
        status=status_filter,
    )

    return {"total": total, "skip": skip, "limit": limit, "data": pos}


@router.get("/{po_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(
    po_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a single Purchase Order by ID (includes line items)."""
    service = PurchaseOrderService(db)
    try:
        return service.get_po_by_id(po_id, current_user["company_id"])
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.patch("/{po_id}/deliver", response_model=PurchaseOrderResponse)
def mark_po_delivered(
    po_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    """
    Action Endpoint: Marks a PO as delivered and physically increments inventory.
    This executes a transaction safely calling the InventoryService.
    """
    service = PurchaseOrderService(db)
    try:
        po = service.mark_po_as_delivered(po_id, current_user["company_id"])
        db.commit()
        return po
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        # e.g., "This PO has already been delivered."
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
