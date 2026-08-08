from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_type: str
    severity: str
    status: str
    subject_type: str
    subject_id: UUID
    title: str
    # The evidence that fired it. Always sent, so the UI can answer "why am I
    # seeing this?" without a second request.
    detail: Dict[str, Any]
    triggered_by_event_id: Optional[UUID] = None
    created_at: datetime
    resolved_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None


class PaginatedAlertResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[AlertResponse]
    # Open counts by severity, sent alongside the page so a filtered view can
    # still show what it is hiding.
    open_counts: Dict[str, int]
