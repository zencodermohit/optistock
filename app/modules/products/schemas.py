import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
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
    # Constrained to a path on this origin. A full URL would be accepted by the
    # column and then blocked by the browser as mixed content if it were http,
    # or silently break the page if the remote host disappeared; neither
    # failure is visible from here, so the shape is refused at the edge.
    image_url: Optional[str] = Field(None, max_length=500)

    @field_validator("image_url")
    @classmethod
    def _path_on_this_origin(cls, value: Optional[str]) -> Optional[str]:
        """A path here, never a URL.

        A full URL would be accepted by the column and then fail somewhere the
        server cannot see it: an http one is blocked by the browser as mixed
        content on an https page, and a remote one breaks the day that host
        goes away. Both look like a working catalogue in development.

        Written as a validator rather than a `pattern` because pydantic v2
        compiles patterns with the Rust regex crate, which has no lookahead --
        so the ".." check cannot be expressed there.
        """
        if value is None:
            return value
        if not value.startswith("/") or ".." in value:
            raise ValueError("image_url must be an absolute path on this origin")
        if not re.fullmatch(r"/[\w\-./]+", value):
            raise ValueError("image_url contains characters that are not allowed")
        return value


# What the API returns to the client
class BarcodeLink(BaseModel):
    """Attach the number printed on the article to this product.

    Null is a legitimate value: it unlinks, which is how you recover from
    scanning the wrong packet onto the wrong row without needing a second
    endpoint to undo it.
    """

    model_config = ConfigDict(extra="forbid")
    barcode: Optional[str] = Field(None, min_length=6, max_length=64)

    @field_validator("barcode")
    @classmethod
    def _plausible_symbol(cls, value: Optional[str]) -> Optional[str]:
        """Reject what no scanner could have produced.

        Deliberately loose. This accepts EAN-13, UPC-A, EAN-8 and the
        alphanumeric Code 128 a warehouse prints for itself, because rejecting
        anything a real scanner can read would make the feature useless in the
        one situation it exists for. It refuses whitespace and control
        characters, which is all that separates a scan from a paste.
        """
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if any(character.isspace() for character in cleaned):
            raise ValueError("A barcode contains no spaces.")
        if not cleaned.isprintable():
            raise ValueError("That is not a readable barcode.")
        return cleaned


class ProductResponse(ProductBase):
    id: UUID
    sku: str
    company_id: UUID
    status: str
    # The manufacturer's number, once somebody has physically scanned the
    # article. Null for almost every row, and that is the resting state.
    barcode: Optional[str] = None
    # A path under this origin, or null. Null is an ordinary state -- a product
    # without a photograph is still a product -- so the client renders a
    # lettered tile rather than treating it as an error.
    image_url: Optional[str] = None
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
