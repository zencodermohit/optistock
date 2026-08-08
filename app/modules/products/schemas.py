from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from uuid import UUID
from datetime import datetime
from decimal import Decimal


# Base properties shared across multiple schemas
class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    unit_cost: Decimal = Field(..., ge=0)
    selling_price: Decimal = Field(..., ge=0)


# What the client sends when creating a product
class ProductCreate(ProductBase):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(..., min_length=3, max_length=50)


# What the client sends when updating a product (all fields optional)
class ProductUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    category: Optional[str] = Field(None, max_length=100)
    unit_cost: Optional[Decimal] = Field(None, ge=0)
    selling_price: Optional[Decimal] = Field(None, ge=0)
    status: Optional[str] = Field(None, pattern="^(active|archived|discontinued)$")


# What the API returns to the client
class ProductResponse(ProductBase):
    id: UUID
    sku: str
    company_id: UUID
    status: str
    # Populated by the nightly ABC analysis; null until the product has sold.
    abc_class: Optional[str] = None
    abc_calculated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = (
            True  # Tells Pydantic to read data directly from the SQLAlchemy ORM model
        )


class PaginatedProductsResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: list[ProductResponse]
