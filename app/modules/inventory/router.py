from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import get_current_user, RequireRole
from app.core.exceptions import OptiStockException

from app.modules.inventory.schemas import (
    InventoryAdjustmentCreate,
    InventoryResponse,
    PaginatedInventoryResponse,
)
from app.modules.inventory.service import InventoryService

router = APIRouter(prefix="/api/v1/inventory", tags=["Inventory"])


@router.get("/", response_model=PaginatedInventoryResponse)
def get_inventory_levels(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    warehouse_id: Optional[UUID] = Query(
        None, description="Filter by a specific warehouse"
    ),
    search: Optional[str] = Query(None, description="Match on product SKU or name"),
    low_only: bool = Query(
        False, description="Only lines at or below their reorder point"
    ),
    db: Session = Depends(get_db),
    # Any logged-in user can view stock levels
    current_user: dict = Depends(get_current_user),
):
    """Get paginated inventory levels across warehouses, lowest stock first."""
    service = InventoryService(db)
    items, total = service.get_inventory(
        company_id=UUID(current_user["company_id"]),
        skip=skip,
        limit=limit,
        warehouse_id=warehouse_id,
        search=search,
        low_only=low_only,
    )

    return {"total": total, "skip": skip, "limit": limit, "data": items}


@router.get("/traces")
def get_inventory_traces(
    days: int = Query(30, ge=7, le=90, description="Window length in days"),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Daily closing quantity per stock line, for the sparkline on each row.

    Served separately from the stock list rather than embedded in it. The list
    is the page's blocking request and must stay fast; a trace is decoration
    that can arrive a moment later without holding the table back. Keyed by
    inventory id so the client joins them to rows it already has.
    """
    service = InventoryService(db)
    traces = service.get_traces(
        company_id=UUID(current_user["company_id"]),
        days=days,
    )
    return {
        "days": days,
        "traces": {
            str(inventory_id): series for inventory_id, series in traces.items()
        },
    }


@router.post("/adjust", response_model=InventoryResponse)
def manual_inventory_adjustment(
    adjustment: InventoryAdjustmentCreate,
    db: Session = Depends(get_db),
    # RBAC: Extremely strict! Only admins can arbitrarily change stock numbers.
    current_user: dict = Depends(RequireRole(["admin"])),
):
    """
    Action Endpoint: Manually correct inventory levels (shrinkage, damage, cycle counts).
    This strictly requires the 'admin' role.
    """
    # Prevent pointless database calls
    if adjustment.quantity_change == 0:
        raise HTTPException(status_code=400, detail="quantity_change cannot be zero.")

    service = InventoryService(db)

    try:
        # We pass the required reason directly into the ledger's reference_id
        result = service.adjust_inventory(
            product_id=adjustment.product_id,
            warehouse_id=adjustment.warehouse_id,
            company_id=UUID(current_user["company_id"]),
            quantity_change=adjustment.quantity_change,
            movement_type="manual_adjustment",
            reference_id=f"Reason: {adjustment.reason}",
        )
        db.commit()
        # Re-read through the enriched query so the caller gets a row shaped
        # exactly like the ones in the list response and can swap it in place.
        return service.get_inventory_line(
            inventory_id=result.id,
            company_id=UUID(current_user["company_id"]),
        )
    except OptiStockException as e:
        db.rollback()
        # e.g., "Cannot deduct 100 units. Only 50 available."
        raise HTTPException(status_code=400, detail=e.message)
