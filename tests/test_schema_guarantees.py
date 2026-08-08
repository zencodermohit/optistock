"""Database-level guarantees for the event backbone.

These tables have no application code yet — that arrives in weeks 2 and 4. The
guarantees below are enforced by the schema itself, so they are worth pinning
now: if a later migration quietly drops one of these indexes, the alerting layer
would start producing duplicate rows and nothing else would notice.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.modules.alerts.models import (
    STATUS_DISMISSED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Alert,
)
from app.modules.events.models import EventOutbox


def _alert(company, subject_id, status=STATUS_OPEN, alert_type="low_stock"):
    return Alert(
        company_id=company.id,
        alert_type=alert_type,
        severity="warning",
        status=status,
        subject_type="inventory",
        subject_id=subject_id,
        title="Stock below reorder point",
        detail={"quantity": 2, "reorder_point": 10},
    )


# ---------------------------------------------------------------------------
# Alert de-duplication
# ---------------------------------------------------------------------------
def test_only_one_open_alert_per_subject(db_session, company):
    """A condition that keeps re-firing must not produce a wall of duplicates."""
    subject = uuid.uuid4()
    db_session.add(_alert(company, subject))
    db_session.commit()

    db_session.add(_alert(company, subject))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_a_resolved_alert_does_not_block_a_new_one(db_session, company):
    """The index is partial on status='open', so the same condition can
    legitimately re-open later without tripping over its own history."""
    subject = uuid.uuid4()
    db_session.add(_alert(company, subject, status=STATUS_RESOLVED))
    db_session.add(_alert(company, subject, status=STATUS_DISMISSED))
    db_session.commit()

    db_session.add(_alert(company, subject, status=STATUS_OPEN))
    db_session.commit()  # must not raise

    assert db_session.query(Alert).filter(Alert.subject_id == subject).count() == 3


def test_different_alert_types_on_one_subject_coexist(db_session, company):
    """Low stock and an anomaly on the same row are two separate concerns."""
    subject = uuid.uuid4()
    db_session.add(_alert(company, subject, alert_type="low_stock"))
    db_session.add(_alert(company, subject, alert_type="anomaly"))
    db_session.commit()

    assert db_session.query(Alert).filter(Alert.subject_id == subject).count() == 2


def test_alert_status_vocabulary_is_enforced(db_session, company):
    db_session.add(_alert(company, uuid.uuid4(), status="whatever"))
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_alert_severity_vocabulary_is_enforced(db_session, company):
    alert = _alert(company, uuid.uuid4())
    alert.severity = "catastrophic"
    db_session.add(alert)
    with pytest.raises(IntegrityError):
        db_session.commit()


# ---------------------------------------------------------------------------
# Outbox
# ---------------------------------------------------------------------------
def test_outbox_sequence_preserves_insertion_order(db_session, company):
    """Replay depends on a sortable key. A random UUID could not provide one."""
    for i in range(3):
        db_session.add(
            EventOutbox(
                event_id=uuid.uuid4(),
                company_id=company.id,
                event_type="stock.deducted",
                aggregate_type="inventory",
                aggregate_id=uuid.uuid4(),
                payload={"n": i},
            )
        )
        db_session.flush()
    db_session.commit()

    rows = db_session.query(EventOutbox).order_by(EventOutbox.sequence).all()
    assert [r.payload["n"] for r in rows] == [0, 1, 2]
    assert rows[0].sequence < rows[1].sequence < rows[2].sequence


def test_outbox_event_id_is_unique(db_session, company):
    """Consumers de-duplicate on event_id, so it has to actually be unique."""
    shared = uuid.uuid4()
    for _ in range(2):
        db_session.add(
            EventOutbox(
                event_id=shared,
                company_id=company.id,
                event_type="stock.deducted",
                aggregate_type="inventory",
                aggregate_id=uuid.uuid4(),
                payload={},
            )
        )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_new_events_start_unpublished(db_session, company):
    """published_at IS NULL is the entire 'not yet relayed' state machine."""
    event = EventOutbox(
        event_id=uuid.uuid4(),
        company_id=company.id,
        event_type="sale.completed",
        aggregate_type="sale",
        aggregate_id=uuid.uuid4(),
        payload={},
    )
    db_session.add(event)
    db_session.commit()

    assert event.published_at is None
    assert event.occurred_at is not None


# ---------------------------------------------------------------------------
# Reorder point
# ---------------------------------------------------------------------------
def test_reorder_point_defaults_to_zero(
    db_session, company, make_product, make_warehouse, make_stock
):
    """0 means 'not configured', so nothing alerts until someone sets a number."""
    inventory = make_stock(make_product(company), make_warehouse(company), quantity=5)
    db_session.refresh(inventory)
    assert inventory.reorder_point == 0


def test_reorder_point_cannot_be_negative(
    db_session, company, make_product, make_warehouse, make_stock
):
    inventory = make_stock(make_product(company), make_warehouse(company), quantity=5)

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE inventory SET reorder_point = -1 WHERE id = :id"),
            {"id": inventory.id},
        )
        db_session.flush()
