from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class EventResponse(BaseModel):
    """One domain event, as the UI reads it.

    `sequence` is exposed deliberately. It is the only total order the system
    has, so a client that wants "everything after what I already have" asks by
    sequence rather than by timestamp -- several events committed in one
    transaction share a timestamp and cannot be ordered by it.
    """

    model_config = ConfigDict(from_attributes=True)

    sequence: int
    event_id: UUID
    event_type: str
    aggregate_type: str
    aggregate_id: UUID
    payload: Dict[str, Any]
    occurred_at: datetime
    published_at: Optional[datetime] = None


class PaginatedEventResponse(BaseModel):
    total: int
    skip: int
    limit: int
    data: List[EventResponse]


class OutboxHealth(BaseModel):
    """How far behind the relay is.

    Backlog depth and the age of the oldest unpublished event are the two
    numbers that tell you whether the event system is healthy. A backlog that
    grows is a relay that has stopped; a backlog that is large but flat is a
    relay that is merely busy.
    """

    unpublished: int
    published: int
    oldest_unpublished_age_seconds: Optional[float]
