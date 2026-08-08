from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import List


# -----------------------------------------
# Inventory Schemas
# -----------------------------------------
class InventoryAdjustmentCreate(BaseModel):
    """Schema for a human performing a manual stock correction."""

    product_id: UUID
    warehouse_id: UUID
    quantity_change: int = Field(
        ..., description="Positive to add stock, negative to deduct"
    )

    # We force the user to type at least 5 characters to explain WHY they are changing the stock
    reason: str = Field(
        ..., min_length=5, description="Reason for the manual adjustment"
    )


class InventoryResponse(BaseModel):
    """Schema for returning the current stock level."""

    id: UUID
    product_id: UUID
    warehouse_id: UUID
    quantity: int
    last_counted_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedInventoryResponse(BaseModel):
    """Standard paginated response envelope."""

    total: int
    skip: int
    limit: int
    data: List[InventoryResponse]
