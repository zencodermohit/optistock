from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from typing import List
from datetime import datetime


# -----------------------------------------
# Sale Item Schemas
# -----------------------------------------
class SaleItemCreate(BaseModel):
    """Schema for each line item when creating a sale."""

    product_id: UUID
    quantity: int = Field(..., gt=0, description="Must be at least 1 unit")
    unit_price: float = Field(..., gt=0, description="Must be greater than zero")


class SaleItemResponse(BaseModel):
    """Schema for returning a sale item in API responses."""

    id: UUID
    sale_id: UUID
    product_id: UUID
    quantity: int
    unit_price: float

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------
# Sale Schemas
# -----------------------------------------
class SaleCreate(BaseModel):
    """Schema for creating a new sale. The client must provide at least one item."""

    customer_id: UUID
    source_warehouse_id: UUID
    items: List[SaleItemCreate] = Field(
        ..., min_length=1, description="A sale must have at least one item"
    )


class SaleResponse(BaseModel):
    """A sale as it appears in a LIST.

    Deliberately without line items. A page of 50 sales would otherwise drag
    several hundred item rows across the wire that the list view never renders.
    Fetch the detail representation below when you actually need them.
    """

    id: UUID
    company_id: UUID
    customer_id: UUID
    source_warehouse_id: UUID
    status: str
    total_amount: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SaleDetailResponse(SaleResponse):
    """A single sale, with its line items."""

    items: List[SaleItemResponse] = []


# -----------------------------------------
# Paginated Response
# -----------------------------------------
class PaginatedSalesResponse(BaseModel):
    """Standard paginated response envelope for list endpoints."""

    total: int
    skip: int
    limit: int
    data: List[SaleResponse]
