from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import RequireRole, get_current_user
from app.core.exceptions import ResourceNotFoundError
from app.modules.customers.schemas import (
    CustomerCreate,
    CustomerOrdersResponse,
    CustomerResponse,
    CustomerUpdate,
    PaginatedCustomersResponse,
)
from app.modules.customers.service import CustomerService

router = APIRouter(prefix="/api/v1/customers", tags=["Customers"])

# Who may change the customer list. Reads are open to any authenticated user.
CAN_WRITE = RequireRole(["admin", "sales_rep", "supply_chain"])


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    customer_in: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(CAN_WRITE),
):
    """Create a customer.

    Until this existed the sales workflow could not be completed through the
    API at all — a sale requires a customer_id and there was no way to make one.
    """
    service = CustomerService(db)
    try:
        customer = service.create_customer(
            customer_in, UUID(current_user["company_id"])
        )
        db.commit()
        return customer
    except Exception:
        db.rollback()
        raise


@router.get("/", response_model=PaginatedCustomersResponse)
def list_customers(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Match on name or email"),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List this company's customers."""
    service = CustomerService(db)
    customers, total = service.get_customers(
        company_id=UUID(current_user["company_id"]),
        skip=skip,
        limit=limit,
        search=search,
        is_active=is_active,
    )
    return {"total": total, "skip": skip, "limit": limit, "data": customers}


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get a single customer."""
    service = CustomerService(db)
    try:
        return service.get_customer_by_id(customer_id, UUID(current_user["company_id"]))
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/{customer_id}/orders", response_model=CustomerOrdersResponse)
def get_customer_orders(
    customer_id: UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """This customer's order history and lifetime value."""
    service = CustomerService(db)
    try:
        orders, total, lifetime_value = service.get_customer_orders(
            customer_id, UUID(current_user["company_id"]), skip=skip, limit=limit
        )
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)

    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "lifetime_value": lifetime_value,
        "data": orders,
    }


@router.patch("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: UUID,
    customer_in: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(CAN_WRITE),
):
    """Update a customer. Only the fields you send are changed."""
    service = CustomerService(db)
    try:
        customer = service.update_customer(
            customer_id, customer_in, UUID(current_user["company_id"])
        )
        db.commit()
        return customer
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception:
        db.rollback()
        raise


@router.delete("/{customer_id}", response_model=CustomerResponse)
def deactivate_customer(
    customer_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(CAN_WRITE),
):
    """Soft delete — sales reference customers, so history must survive."""
    service = CustomerService(db)
    try:
        customer = service.deactivate_customer(
            customer_id, UUID(current_user["company_id"])
        )
        db.commit()
        return customer
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception:
        db.rollback()
        raise
