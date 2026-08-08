"""Writing domain events — the producer half of the transactional outbox.

Nothing here talks to Redis. A request that both writes to Postgres and
publishes to a broker has to pick which one to do first, and both orders are
wrong: publish-then-commit can announce a sale that gets rolled back, and
commit-then-publish can lose the announcement if the process dies in between.
That is the dual-write problem, and there is no arrangement of two systems that
fixes it.

The outbox sidesteps it. The event is a row in the same database, written in the
same transaction as the change it describes, so the two commit or fail together.
A separate relay reads those rows and publishes them. Delivery becomes
at-least-once rather than exactly-once, which is why every event carries a
stable `event_id` for consumers to de-duplicate on.
"""

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.audit.listener import ACTOR_KEY
from app.modules.events.models import EventOutbox


def record_event(
    db: Session,
    *,
    company_id: UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: UUID,
    payload: Dict[str, Any],
    actor_user_id: Optional[UUID] = None,
) -> EventOutbox:
    """Stage a domain event alongside the change that caused it.

    Flushes but never commits, the same contract every service in this codebase
    follows: the caller owns the transaction. That is the entire point — if the
    caller rolls back, this event disappears with it, and an event describing
    something that never happened is worse than no event at all.
    """
    if actor_user_id is None:
        # The audit listener already tags each request's session with who is
        # acting. Reading it here means callers do not have to thread a user id
        # through every service signature just to attribute an event.
        actor = db.info.get(ACTOR_KEY)
        if actor:
            actor_user_id = actor.get("user_id")

    event = EventOutbox(
        company_id=company_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        actor_user_id=actor_user_id,
    )
    db.add(event)
    db.flush()
    return event
