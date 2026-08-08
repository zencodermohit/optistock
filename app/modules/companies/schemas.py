from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID
from datetime import datetime
from typing import List, Optional


class CompanyCreate(BaseModel):
    """Schema for creating a new company (tenant onboarding)."""

    name: str = Field(
        ..., min_length=2, max_length=255, description="Company legal name"
    )


class CompanyUpdate(BaseModel):
    """Schema for updating a company."""

    name: Optional[str] = Field(None, min_length=2, max_length=255)
    is_active: Optional[bool] = None


class CompanyResponse(BaseModel):
    """Schema for returning a company."""

    id: UUID
    name: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedCompaniesResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[CompanyResponse]
