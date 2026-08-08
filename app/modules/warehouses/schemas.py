from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from uuid import UUID


class WarehouseBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    location_code: str = Field(..., min_length=2, max_length=50)
    capacity_units: int = Field(..., gt=0)


class WarehouseCreate(WarehouseBase):
    model_config = ConfigDict(extra="forbid")
    pass


class WarehouseUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    location_code: Optional[str] = None
    capacity_units: Optional[int] = Field(None, gt=0)
    is_active: Optional[bool] = None


class WarehouseResponse(WarehouseBase):
    id: UUID
    company_id: UUID
    is_active: bool

    class Config:
        from_attributes = True


class PaginatedWarehousesResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: list[WarehouseResponse]
