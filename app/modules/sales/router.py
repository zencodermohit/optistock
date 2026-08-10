from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID

from app.core.database import get_db
from app.core.dependencies import get_current_user, RequireRole
from app.modules.users.models import User
from app.core.exceptions import OptiStockException, ResourceNotFoundError

from app.modules.sales.schemas import (
    PaginatedSalesResponse,
    SaleCreate,
    SaleDetailResponse,
    SaleResponse,
)
from app.modules.sales.service import SaleService

router = APIRouter(prefix="/api/v1/sales", tags=["Sales"])


@router.post("/", response_model=SaleResponse, status_code=201)
def create_sale(
    sale_in: SaleCreate,
    db: Session = Depends(get_db),
    # RBAC: Only admins or supply chain managers can create sales
    current_user_dict: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    """
    Create a new sale. Automatically deducts inventory.
    Requires 'admin' or 'supply_chain' role.
    """
    service = SaleService(db)

    # We must fetch the actual User object from the database to get their company_id
    user = db.query(User).filter(User.id == current_user_dict["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    try:
        # We tie the sale to the company the user belongs to
        sale = service.create_sale(sale_in, user.company_id)
        db.commit()
        return sale
    except OptiStockException as e:
        db.rollback()
        # If InventoryService throws InsufficientStockError, we catch it
        # and translate it into a clean HTTP 400 Bad Request.
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.get("/", response_model=PaginatedSalesResponse)
def get_sales(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(50, ge=1, le=100, description="Max records to return"),
    status: Optional[str] = Query(
        None, description="Filter by status (e.g., completed)"
    ),
    db: Session = Depends(get_db),
    # RBAC: Any authenticated user can VIEW sales
    current_user_dict: dict = Depends(get_current_user),
):
    """
    Get a paginated list of sales.
    """
    service = SaleService(db)
    sales, total = service.get_sales(
        company_id=current_user_dict["company_id"],
        skip=skip,
        limit=limit,
        status=status,
    )

    # Notice this perfectly matches our PaginatedSalesResponse schema!
    return {"total": total, "skip": skip, "limit": limit, "data": sales}


@router.get("/ledger")
def get_ledger(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=200),
    status: Optional[str] = Query(None, description="e.g. completed"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Sales with customer and warehouse names joined in, plus page totals.

    Above /{sale_id} for exactly the reason the comment below spells out.
    """
    rows, total, summary = SaleService(db).ledger(
        company_id=UUID(current_user["company_id"]),
        skip=skip,
        limit=limit,
        status=status,
    )
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "summary": summary,
        "data": rows,
    }


# Parameterised path last. FastAPI matches in declaration order and stops at the
# first hit, so a literal route added later (e.g. /summary) would be swallowed
# by /{sale_id} if this sat above it.
@router.get("/{sale_id}", response_model=SaleDetailResponse)
def get_sale(
    sale_id: UUID,
    db: Session = Depends(get_db),
    current_user_dict: dict = Depends(get_current_user),
):
    """Get a single sale, including its line items."""
    service = SaleService(db)
    try:
        return service.get_sale_by_id(sale_id, UUID(current_user_dict["company_id"]))
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)
