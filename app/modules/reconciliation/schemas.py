from pydantic import BaseModel, ConfigDict, Field
from uuid import UUID
from datetime import datetime
from typing import List, Optional


# -----------------------------------------
# Reconciliation Item Schemas
# -----------------------------------------
class ReconciliationItemBase(BaseModel):
    """Schema for a single product being counted."""

    product_id: UUID
    expected_quantity: int = Field(
        ..., ge=0, description="Quantity the system thinks we have"
    )
    actual_quantity: int = Field(
        ..., ge=0, description="Quantity physically counted on the shelf"
    )
    discrepancy_reason: Optional[str] = Field(
        None, description="E.g., damaged, lost, data_entry_error"
    )


class ReconciliationItemResponse(ReconciliationItemBase):
    id: UUID
    reconciliation_id: UUID

    model_config = ConfigDict(from_attributes=True)


# -----------------------------------------
# Reconciliation Schemas
# -----------------------------------------
class ReconciliationCreate(BaseModel):
    """Schema for submitting a cycle count batch."""

    warehouse_id: UUID
    items: List[ReconciliationItemBase] = Field(
        ..., min_length=1, description="Must count at least 1 item"
    )


class ReconciliationResponse(BaseModel):
    """Schema for returning the reconciliation details."""

    id: UUID
    company_id: UUID
    warehouse_id: UUID
    status: str
    created_at: datetime

    items: List[ReconciliationItemResponse] = []

    model_config = ConfigDict(from_attributes=True)


class PaginatedReconciliationsResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[ReconciliationResponse]
