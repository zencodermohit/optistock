from pydantic import BaseModel, UUID4
from typing import Optional, Dict, Any
from datetime import datetime


class AuditLogBase(BaseModel):
    user_id: Optional[UUID4] = None
    company_id: UUID4
    entity_name: str
    entity_id: UUID4
    action: str
    old_values: Optional[Dict[str, Any]] = None
    new_values: Optional[Dict[str, Any]] = None


class AuditLogCreate(AuditLogBase):
    pass


class AuditLogResponse(AuditLogBase):
    id: UUID4
    timestamp: datetime

    class Config:
        from_attributes = True
