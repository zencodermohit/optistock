from pydantic import BaseModel, EmailStr, Field, ConfigDict
from uuid import UUID
from typing import Optional, List


# -----------------------------------------
# Supplier Base & Core Schemas
# -----------------------------------------
class SupplierBase(BaseModel):
    """Fields common to creating, updating, and reading a supplier."""

    name: str = Field(
        ..., min_length=2, max_length=255, description="The legal name of the supplier"
    )
    # EmailStr mathematically guarantees it has an @ and a valid domain format
    contact_email: Optional[EmailStr] = None


class SupplierCreate(SupplierBase):
    """Schema for creating a new supplier."""

    pass


class SupplierUpdate(BaseModel):
    """Schema for updating an existing supplier. All fields are optional."""

    name: Optional[str] = Field(None, min_length=2, max_length=255)
    contact_email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


# -----------------------------------------
# Supplier Responses
# -----------------------------------------
class SupplierResponse(SupplierBase):
    """Schema for returning a supplier to the client."""

    id: UUID
    company_id: UUID
    reliability_score: (
        float  # Kept read-only! Clients cannot set their own reliability score.
    )
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class PaginatedSuppliersResponse(BaseModel):
    """Standard paginated response envelope."""

    total: int
    skip: int
    limit: int
    data: List[SupplierResponse]
