from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from typing import List, Optional
from datetime import date, datetime


# -----------------------------------------
# PO Item Schemas
# -----------------------------------------
class POItemBase(BaseModel):
    """Schema for line items inside a PO."""

    product_id: UUID
    quantity: int = Field(..., gt=0, description="Must order at least 1 unit")
    unit_price: float = Field(..., gt=0, description="Cost per unit from supplier")


class POItemResponse(POItemBase):
    id: UUID
    po_id: UUID

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------
# Purchase Order Schemas
# -----------------------------------------
class PurchaseOrderCreate(BaseModel):
    """Schema for creating a new Purchase Order."""

    supplier_id: UUID
    destination_warehouse_id: UUID
    expected_delivery_date: Optional[date] = None
    items: List[POItemBase] = Field(
        ..., min_length=1, description="A PO must have items"
    )


class PurchaseOrderResponse(BaseModel):
    """Schema for returning a PO to the client."""

    id: UUID
    company_id: UUID
    supplier_id: UUID
    destination_warehouse_id: UUID
    status: str
    expected_delivery_date: Optional[date]
    total_amount: float
    created_at: datetime

    # We include the line items directly in the response
    items: List[POItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class PaginatedPOResponse(BaseModel):
    """Standard paginated response envelope."""

    total: int
    skip: int
    limit: int
    data: List[PurchaseOrderResponse]
