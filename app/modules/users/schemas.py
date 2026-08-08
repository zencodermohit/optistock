from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Token(BaseModel):
    access_token: str
    token_type: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    """Tenant-admin input for provisioning a user in their own company."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Literal[
        "admin", "finance", "supply_chain", "warehouse_manager", "sales_rep", "analyst"
    ] = "analyst"


class UserResponse(BaseModel):
    id: str
    email: str
    company_id: str
    role: str
    is_active: bool

    class Config:
        from_attributes = True
