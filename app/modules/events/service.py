from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.modules.events.models import EventOutbox


class EventService:
    """Reads the outbox.

    The outbox is the durable record of what happened; Redis only carries it to
    consumers and trims itself. So history queries come from here, and the live
    stream comes from Redis -- a page showing both is reading one log through
    two doors.
    """

    def __init__(self, db: Session):
        self.db = db

    def list_events(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        event_type: Optional[str] = None,
        after_sequence: Optional[int] = None,
    ) -> Tuple[List[EventOutbox], int]:
        query = self.db.query(EventOutbox).filter(EventOutbox.company_id == company_id)

        if event_type:
            query = query.filter(EventOutbox.event_type == event_type)
        if after_sequence is not None:
            query = query.filter(EventOutbox.sequence > after_sequence)

        total = query.count()
        events = (
            query.order_by(EventOutbox.sequence.desc()).offset(skip).limit(limit).all()
        )
        return events, total

    def health(self, company_id: UUID) -> dict:
        """Relay lag, for the operator and for the demo.

        Scoped to the tenant like everything else, so one company's backlog is
        never visible to another even though they share a table.
        """
        rows = (
            self.db.query(
                func.count(EventOutbox.sequence).label("total"),
                func.count(EventOutbox.published_at).label("published"),
                func.min(func.coalesce(EventOutbox.occurred_at, None)).label("oldest"),
            )
            .filter(
                EventOutbox.company_id == company_id,
                EventOutbox.published_at.is_(None),
            )
            .one()
        )
        unpublished = rows.total or 0

        published = (
            self.db.query(func.count(EventOutbox.sequence))
            .filter(
                EventOutbox.company_id == company_id,
                EventOutbox.published_at.isnot(None),
            )
            .scalar()
            or 0
        )

        age = None
        if rows.oldest is not None:
            oldest = rows.oldest
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - oldest).total_seconds()

        return {
            "unpublished": unpublished,
            "published": published,
            "oldest_unpublished_age_seconds": age,
        }
