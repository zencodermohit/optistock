from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import List, Optional


# -----------------------------------------
# Transfer Item Schemas
# -----------------------------------------
class TransferItemBase(BaseModel):
    """Schema for a single product being transferred."""

    product_id: UUID
    quantity: int = Field(..., gt=0, description="Quantity must be greater than zero")


class TransferItemResponse(TransferItemBase):
    id: UUID
    transfer_id: UUID

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------
# Transfer Schemas
# -----------------------------------------
class TransferCreate(BaseModel):
    """Schema for requesting a new transfer."""

    source_warehouse_id: UUID
    destination_warehouse_id: UUID
    items: List[TransferItemBase] = Field(
        ..., min_length=1, description="Must transfer at least 1 item"
    )


class TransferResponse(BaseModel):
    """Schema for returning transfer details."""

    id: UUID
    company_id: UUID
    source_warehouse_id: UUID
    destination_warehouse_id: UUID
    status: str
    shipped_at: Optional[datetime]
    received_at: Optional[datetime]
    created_at: datetime

    items: List[TransferItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class PaginatedTransfersResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[TransferResponse]
