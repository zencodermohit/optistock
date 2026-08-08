from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class CustomerBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    email: Optional[EmailStr] = None


class CustomerCreate(CustomerBase):
    # extra="forbid" so a caller cannot smuggle company_id into the body and
    # create a customer inside another tenant. Tenant identity comes from the
    # token, never from the request.
    model_config = ConfigDict(extra="forbid")


class CustomerUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(None, min_length=2, max_length=255)
    email: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class CustomerResponse(CustomerBase):
    id: UUID
    company_id: UUID
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class PaginatedCustomersResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[CustomerResponse]


class CustomerOrderResponse(BaseModel):
    """A sale in this customer's history — deliberately lighter than SaleDetail."""

    id: UUID
    status: str
    total_amount: float
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerOrdersResponse(BaseModel):
    total: int
    skip: int
    limit: int
    lifetime_value: float
    data: List[CustomerOrderResponse]
