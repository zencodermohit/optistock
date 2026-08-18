from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import RequireRole, get_current_user
from app.modules.users.models import User
from app.core.exceptions import OptiStockException, ResourceNotFoundError

from app.modules.suppliers.schemas import (
    SupplierCreate,
    SupplierUpdate,
    SupplierResponse,
    PaginatedSuppliersResponse,
)
from app.modules.suppliers.service import SupplierService

from app.modules.analytics.readmodels import supplier_scorecard

router = APIRouter(prefix="/api/v1/suppliers", tags=["Suppliers"])


def get_current_db_user(
    current_user_dict: dict = Depends(get_current_user), db: Session = Depends(get_db)
) -> User:
    """Helper dependency to fetch the full User object for company_id access."""
    user = db.query(User).filter(User.id == current_user_dict["id"]).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("/", response_model=SupplierResponse, status_code=status.HTTP_201_CREATED)
def create_supplier(
    supplier_in: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_db_user),
    _: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    """Create a new supplier."""
    service = SupplierService(db)
    try:
        supplier = service.create_supplier(supplier_in, current_user.company_id)
        db.commit()
        return supplier
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=409, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.get("/", response_model=PaginatedSuppliersResponse)
def get_suppliers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a paginated list of suppliers."""
    service = SupplierService(db)
    suppliers, total = service.get_suppliers(
        company_id=UUID(current_user["company_id"]),
        skip=skip,
        limit=limit,
        is_active=is_active,
    )

    return {"total": total, "skip": skip, "limit": limit, "data": suppliers}


@router.get("/scorecard")
def get_scorecard(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Suppliers with the order history that justifies their reliability score.

    Above /{supplier_id}: FastAPI matches in declaration order, and below it
    "scorecard" would be read as a supplier id and rejected as a bad UUID.
    """
    return {"data": supplier_scorecard(db, UUID(current_user["company_id"]))}


@router.get("/{supplier_id}", response_model=SupplierResponse)
def get_supplier(
    supplier_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a single supplier by ID."""
    service = SupplierService(db)
    try:
        return service.get_supplier_by_id(supplier_id, UUID(current_user["company_id"]))
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.patch("/{supplier_id}", response_model=SupplierResponse)
def update_supplier(
    supplier_id: UUID,
    supplier_in: SupplierUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    """Update a supplier."""
    service = SupplierService(db)
    try:
        supplier = service.update_supplier(
            supplier_id, supplier_in, UUID(current_user["company_id"])
        )
        db.commit()
        return supplier
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.delete("/{supplier_id}", response_model=SupplierResponse)
def delete_supplier(
    supplier_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    """Soft delete a supplier."""
    service = SupplierService(db)
    try:
        supplier = service.delete_supplier(
            supplier_id, UUID(current_user["company_id"])
        )
        db.commit()
        return supplier
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
