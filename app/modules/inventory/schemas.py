from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import List, Optional


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
    """A stock level, with enough context to render without further lookups.

    The names are denormalised into the response on purpose. Returning bare
    foreign keys would force the client to fetch every product and warehouse
    just to label a table — an N+1 moved from the server to the browser, which
    is the worse place for it.
    """

    id: UUID
    product_id: UUID
    warehouse_id: UUID
    quantity: int
    last_counted_at: datetime

    sku: str
    product_name: str
    warehouse_name: str
    category: Optional[str] = None
    abc_class: Optional[str] = None
    reorder_point: int
    #: Computed server-side so every client agrees on what "low" means.
    is_low: bool

    model_config = ConfigDict(from_attributes=True)


class PaginatedInventoryResponse(BaseModel):
    """Standard paginated response envelope."""

    total: int
    skip: int
    limit: int
    data: List[InventoryResponse]
