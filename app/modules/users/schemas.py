from typing import Literal
from uuid import UUID

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
    # Spelled out rather than generated so it appears in the OpenAPI docs, but
    # kept in step with app.core.roles.TENANT_ASSIGNABLE_ROLES by a test.
    # "platform_admin" is absent on purpose: it grants cross-tenant access, so a
    # tenant admin able to assign it could escalate to platform operator.
    role: Literal[
        "admin", "finance", "supply_chain", "warehouse_manager", "sales_rep", "analyst"
    ] = "analyst"


class UserResponse(BaseModel):
    # UUID, not str. The columns are postgresql.UUID, so declaring these as str
    # made FastAPI reject its own response and return a 500 — registration had
    # never actually worked end to end, because nothing exercised it.
    id: UUID
    email: str
    company_id: UUID
    role: str
    is_active: bool

    class Config:
        from_attributes = True
