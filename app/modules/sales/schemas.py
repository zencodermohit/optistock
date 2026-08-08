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
    """Schema for returning a sale in API responses."""

    id: UUID
    company_id: UUID
    customer_id: UUID
    source_warehouse_id: UUID
    status: str
    total_amount: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------
# Paginated Response
# -----------------------------------------
class PaginatedSalesResponse(BaseModel):
    """Standard paginated response envelope for list endpoints."""

    total: int
    skip: int
    limit: int
    data: List[SaleResponse]
