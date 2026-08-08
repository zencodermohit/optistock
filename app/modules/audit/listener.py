"""Automatic audit logging via a SQLAlchemy flush listener.

Why a listener rather than explicit ``AuditService.log_action`` calls
--------------------------------------------------------------------
The audit table, its migration and its read endpoint all existed already. What
was missing was any call site at all — ``log_action`` was never invoked, so the
compliance trail was permanently empty while appearing fully built.

Sprinkling explicit calls through every service would fix today's gap and
recreate it the moment someone adds a new mutating endpoint and forgets. A
``before_flush`` listener records anything that reaches the database, so being
audited is the default rather than something each author must remember.

The acting user arrives via ``session.info["audit_actor"]``, set by
``get_current_user``. A ContextVar would look tidier but does not survive
FastAPI running sync dependencies in a worker thread — each ``run_in_threadpool``
call gets a *copy* of the context, so a value set inside the dependency would be
discarded before the endpoint ran. The session is per-request and shared between
the dependency and the endpoint, which makes it the reliable carrier.

Flushes with no actor — background jobs, seed scripts, test fixtures — are
skipped, since there is no one to attribute the change to.
"""

import logging
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.modules.audit.models import AuditLog

logger = logging.getLogger(__name__)

ACTOR_KEY = "audit_actor"

# Aggregate roots worth recording. Deliberately excluded:
#   AuditLog          — would recurse
#   InventoryMovement — already an immutable ledger of the same events
#   Recommendation    — machine-generated in bulk every night; pure noise here
AUDITED_TABLES = {
    "products",
    "warehouses",
    "suppliers",
    "inventory",
    "sales",
    "purchase_orders",
    "transfers",
    "reconciliations",
    "users",
    "companies",
}


def _jsonable(value):
    """Coerce a column value into something the JSON column can hold."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return str(value)


def _column_values(obj) -> dict:
    state = inspect(obj)
    return {
        attr.key: _jsonable(getattr(obj, attr.key, None))
        for attr in state.mapper.column_attrs
    }


def _changed_values(obj) -> tuple[dict, dict]:
    """Old/new values for the columns that actually changed.

    Reads ``attr.history`` rather than ``load_history()`` so inspecting an object
    never triggers a lazy load — an audit hook must not issue extra queries
    mid-flush.
    """
    state = inspect(obj)
    old, new = {}, {}

    for attr in state.mapper.column_attrs:
        history = state.attrs[attr.key].history
        if not history.has_changes():
            continue
        old[attr.key] = _jsonable(history.deleted[0]) if history.deleted else None
        new[attr.key] = _jsonable(history.added[0]) if history.added else None

    return old, new


def _is_audited(obj) -> bool:
    return getattr(obj, "__tablename__", None) in AUDITED_TABLES


def _entry(actor, obj, action, old_values, new_values) -> AuditLog:
    return AuditLog(
        user_id=actor["user_id"],
        company_id=actor["company_id"],
        entity_name=obj.__tablename__,
        entity_id=obj.id,
        action=action,
        old_values=old_values or None,
        new_values=new_values or None,
    )


def record_changes(session: Session, flush_context=None, instances=None) -> None:
    """before_flush hook: append an AuditLog row per tracked change."""
    actor = session.info.get(ACTOR_KEY)
    if not actor:
        return

    entries = []

    for obj in session.new:
        if not _is_audited(obj):
            continue
        # Primary keys use a Python-side `default=uuid.uuid4`, which is applied
        # DURING flush — i.e. after this hook. Assign it now so the audit row can
        # reference the entity. Same value the default would have produced.
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        _, new_values = _changed_values(obj)
        entries.append(_entry(actor, obj, "CREATE", None, new_values))

    for obj in session.dirty:
        if not _is_audited(obj) or not session.is_modified(
            obj, include_collections=False
        ):
            continue
        old_values, new_values = _changed_values(obj)
        if not new_values:
            continue
        entries.append(_entry(actor, obj, "UPDATE", old_values, new_values))

    for obj in session.deleted:
        if not _is_audited(obj):
            continue
        entries.append(_entry(actor, obj, "DELETE", _column_values(obj), None))

    for entry in entries:
        session.add(entry)


def set_actor(session: Session, user_id, company_id) -> None:
    """Tell this session who is responsible for the changes it is about to make."""
    session.info[ACTOR_KEY] = {
        "user_id": uuid.UUID(str(user_id)),
        "company_id": uuid.UUID(str(company_id)),
    }


def register_audit_listener() -> None:
    """Attach the hook to every Session in the process. Safe to call twice."""
    if not event.contains(Session, "before_flush", record_changes):
        event.listen(Session, "before_flush", record_changes)
        logger.info("Audit listener registered.")
