"""Keeping the daily metrics projection current from the event stream.

Registered separately from the alert handlers so the two are genuinely
independent: a broken alert rule must not stop the dashboard updating, and
`dispatch` runs each handler in its own try block precisely so that holds.

Note what these handlers are NOT idempotent against: replaying the same event
twice would double-count it. That is deliberate rather than overlooked --
counters cannot be made naturally idempotent the way "raise an alert" can, and
the honest answer for a projection is that it is rebuildable. A duplicate skews
one day until the next rebuild corrects it, which is a very different cost from
an alert firing twice.
"""

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.analytics.projections import apply_movement, apply_sale
from app.modules.events import types as event_types
from app.workers.consumers import on

logger = logging.getLogger(__name__)


def _day(event: dict):
    """The calendar day an event belongs to, from the event itself.

    Not `date.today()`: a consumer catching up after an outage would file
    yesterday's events under today and quietly move revenue between days.
    """
    occurred = event.get("occurred_at")
    if not occurred:
        return None
    return datetime.fromisoformat(occurred).date()


@on(event_types.SALE_COMPLETED)
def project_sale(db: Session, event: dict) -> None:
    day = _day(event)
    if day is None:
        return
    apply_sale(db, UUID(event["company_id"]), day, event.get("payload", {}))


@on(event_types.STOCK_MOVED)
def project_movement(db: Session, event: dict) -> None:
    day = _day(event)
    if day is None:
        return
    apply_movement(db, UUID(event["company_id"]), day, event.get("payload", {}))
