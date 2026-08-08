"""The consumer half: events in, alerts out.

Handlers are driven through `dispatch` with decoded events rather than through a
running consumer group. The logic worth testing is what an event does to the
database; Redis's own delivery semantics are Redis's to get right.
"""

import uuid

import pytest

from app.modules.alerts.models import STATUS_OPEN, STATUS_RESOLVED, Alert
from app.modules.alerts.service import TYPE_LOW_STOCK, TYPE_OUT_OF_STOCK, AlertService
from app.modules.events import types as event_types
from app.workers.consumers import dispatch

# Importing registers the handlers. Without it dispatch finds nothing and every
# assertion below fails for a reason unrelated to what it is testing.
import app.modules.alerts.handlers  # noqa: F401,E402


def _event(company, event_type, aggregate_id, **payload):
    return {
        "event_id": str(uuid.uuid4()),
        "sequence": "1",
        "company_id": str(company.id),
        "event_type": event_type,
        "aggregate_type": "inventory",
        "aggregate_id": str(aggregate_id),
        "occurred_at": "2026-08-08T10:00:00+00:00",
        "payload": payload,
    }


def _alerts(db_session, company, alert_type=None, status=None):
    query = db_session.query(Alert).filter(Alert.company_id == company.id)
    if alert_type:
        query = query.filter(Alert.alert_type == alert_type)
    if status:
        query = query.filter(Alert.status == status)
    return query.all()


@pytest.fixture
def stock(company, make_warehouse, make_product, make_stock, db_session):
    warehouse = make_warehouse(company)
    product = make_product(company, sku="ALT-001", name="Desk lamp")
    inventory = make_stock(product, warehouse, quantity=4)
    inventory.reorder_point = 10
    db_session.commit()
    return inventory


# ---------------------------------------------------------------------------
# Raising
# ---------------------------------------------------------------------------
def test_crossing_the_reorder_point_raises_a_warning(db_session, company, stock):
    dispatch(
        db_session,
        _event(
            company,
            event_types.STOCK_BELOW_REORDER_POINT,
            stock.id,
            sku="ALT-001",
            product_name="Desk lamp",
            warehouse_name="Main",
            quantity=4,
            reorder_point=10,
        ),
    )

    alerts = _alerts(db_session, company, TYPE_LOW_STOCK)
    assert len(alerts) == 1
    assert alerts[0].severity == "warning"
    assert alerts[0].status == STATUS_OPEN
    # The evidence travels with the alert, so "why am I seeing this?" never
    # needs a second request or a guess.
    assert alerts[0].detail["quantity"] == 4
    assert alerts[0].detail["reorder_point"] == 10


def test_the_same_event_twice_raises_one_alert(db_session, company, stock):
    """At-least-once delivery, handled by shape rather than by memory.

    The relay republishes on crash and a worker can commit then fail to ack, so
    a handler will see duplicates. The partial unique index makes the second
    insert fail, and that failure IS the de-duplication check.
    """
    event = _event(
        company,
        event_types.STOCK_BELOW_REORDER_POINT,
        stock.id,
        product_name="Desk lamp",
        quantity=4,
        reorder_point=10,
    )

    dispatch(db_session, event)
    dispatch(db_session, event)
    dispatch(db_session, dict(event, event_id=str(uuid.uuid4())))

    assert len(_alerts(db_session, company, TYPE_LOW_STOCK)) == 1


def test_a_failed_insert_does_not_poison_the_transaction(db_session, company, stock):
    """The duplicate is swallowed by a SAVEPOINT, not by luck.

    Without begin_nested the IntegrityError would leave the session unusable and
    every later statement in the same handler would fail too.
    """
    service = AlertService(db_session)
    args = dict(
        company_id=company.id,
        alert_type=TYPE_LOW_STOCK,
        severity="warning",
        subject_type="inventory",
        subject_id=stock.id,
        title="Low",
        detail={},
    )

    assert service.open_alert(**args) is not None
    assert service.open_alert(**args) is None
    # The session still works, which is the actual thing being asserted.
    assert service.counts_by_severity(company.id)["warning"] == 1


def test_running_out_supersedes_the_low_stock_warning(db_session, company, stock):
    dispatch(
        db_session,
        _event(
            company,
            event_types.STOCK_BELOW_REORDER_POINT,
            stock.id,
            product_name="Desk lamp",
            quantity=4,
            reorder_point=10,
        ),
    )
    dispatch(
        db_session,
        _event(
            company,
            event_types.STOCK_DEPLETED,
            stock.id,
            product_name="Desk lamp",
            quantity=0,
            reorder_point=10,
        ),
    )

    critical = _alerts(db_session, company, TYPE_OUT_OF_STOCK, STATUS_OPEN)
    assert len(critical) == 1
    assert critical[0].severity == "critical"
    # One physical fact, one open alert. Showing a warning and a critical for
    # the same product would be the system disagreeing with itself.
    assert _alerts(db_session, company, TYPE_LOW_STOCK, STATUS_OPEN) == []
    assert len(_alerts(db_session, company, TYPE_LOW_STOCK, STATUS_RESOLVED)) == 1


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------
def test_restocking_resolves_the_alert(db_session, company, stock):
    """Otherwise the list is a history of everything ever low, not a to-do."""
    dispatch(
        db_session,
        _event(
            company,
            event_types.STOCK_BELOW_REORDER_POINT,
            stock.id,
            product_name="Desk lamp",
            quantity=4,
            reorder_point=10,
        ),
    )
    assert len(_alerts(db_session, company, TYPE_LOW_STOCK, STATUS_OPEN)) == 1

    dispatch(
        db_session,
        _event(
            company,
            event_types.STOCK_MOVED,
            stock.id,
            product_name="Desk lamp",
            quantity_change=200,
            quantity_after=204,
            reorder_point=10,
        ),
    )

    assert _alerts(db_session, company, TYPE_LOW_STOCK, STATUS_OPEN) == []
    assert len(_alerts(db_session, company, TYPE_LOW_STOCK, STATUS_RESOLVED)) == 1


def test_a_movement_that_stays_low_does_not_resolve_anything(
    db_session, company, stock
):
    dispatch(
        db_session,
        _event(
            company,
            event_types.STOCK_BELOW_REORDER_POINT,
            stock.id,
            product_name="Desk lamp",
            quantity=4,
            reorder_point=10,
        ),
    )
    dispatch(
        db_session,
        _event(
            company,
            event_types.STOCK_MOVED,
            stock.id,
            product_name="Desk lamp",
            quantity_change=2,
            quantity_after=6,  # still under 10
            reorder_point=10,
        ),
    )

    assert len(_alerts(db_session, company, TYPE_LOW_STOCK, STATUS_OPEN)) == 1


def test_a_resolved_alert_can_open_again(db_session, company, stock):
    """The unique index only constrains open rows, and that is deliberate."""
    low = _event(
        company,
        event_types.STOCK_BELOW_REORDER_POINT,
        stock.id,
        product_name="Desk lamp",
        quantity=4,
        reorder_point=10,
    )
    restock = _event(
        company,
        event_types.STOCK_MOVED,
        stock.id,
        quantity_change=200,
        quantity_after=204,
        reorder_point=10,
    )

    dispatch(db_session, low)
    dispatch(db_session, restock)
    dispatch(db_session, dict(low, event_id=str(uuid.uuid4())))

    assert len(_alerts(db_session, company, TYPE_LOW_STOCK, STATUS_OPEN)) == 1
    assert len(_alerts(db_session, company, TYPE_LOW_STOCK)) == 2


def test_one_failing_handler_does_not_stop_the_others(db_session, company, stock):
    """Handlers are independent reactions, not a pipeline.

    Letting a broken alert rule suppress an unrelated projection would couple
    them through nothing but registration order.
    """
    from app.workers import consumers

    def explode(db, event):
        raise RuntimeError("this handler is broken")

    consumers._REGISTRY.setdefault(event_types.STOCK_BELOW_REORDER_POINT, []).insert(
        0, explode
    )
    try:
        dispatch(
            db_session,
            _event(
                company,
                event_types.STOCK_BELOW_REORDER_POINT,
                stock.id,
                product_name="Desk lamp",
                quantity=4,
                reorder_point=10,
            ),
        )
    finally:
        consumers._REGISTRY[event_types.STOCK_BELOW_REORDER_POINT].remove(explode)

    assert len(_alerts(db_session, company, TYPE_LOW_STOCK)) == 1


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def test_alert_feed_defaults_to_open_only(
    authenticated_client, db_session, company, stock
):
    service = AlertService(db_session)
    service.open_alert(
        company_id=company.id,
        alert_type=TYPE_LOW_STOCK,
        severity="warning",
        subject_type="inventory",
        subject_id=stock.id,
        title="Low",
        detail={},
    )
    service.resolve_matching(
        company_id=company.id,
        alert_type=TYPE_LOW_STOCK,
        subject_type="inventory",
        subject_id=stock.id,
    )
    db_session.commit()

    default = authenticated_client.get("/api/v1/alerts/").json()
    assert default["total"] == 0

    everything = authenticated_client.get("/api/v1/alerts/?status=all").json()
    assert everything["total"] == 1


def test_dismissing_records_who_did_it(
    authenticated_client, db_session, company, stock, admin_user
):
    alert = AlertService(db_session).open_alert(
        company_id=company.id,
        alert_type=TYPE_LOW_STOCK,
        severity="warning",
        subject_type="inventory",
        subject_id=stock.id,
        title="Low",
        detail={},
    )
    db_session.commit()

    response = authenticated_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

    assert response.status_code == 200
    assert response.json()["status"] == "dismissed"

    db_session.refresh(alert)
    # Dismissed, not resolved: a pile of dismissals is evidence the rule is
    # noisy, and collapsing the two states would destroy that signal.
    assert alert.dismissed_by == admin_user.id
    assert alert.resolved_at is None


def test_dismissing_twice_is_rejected(authenticated_client, db_session, company, stock):
    alert = AlertService(db_session).open_alert(
        company_id=company.id,
        alert_type=TYPE_LOW_STOCK,
        severity="warning",
        subject_type="inventory",
        subject_id=stock.id,
        title="Low",
        detail={},
    )
    db_session.commit()

    authenticated_client.post(f"/api/v1/alerts/{alert.id}/dismiss")
    second = authenticated_client.post(f"/api/v1/alerts/{alert.id}/dismiss")

    assert second.status_code == 400


def test_the_worst_alert_is_listed_first(
    authenticated_client,
    db_session,
    company,
    stock,
    make_warehouse,
    make_product,
    make_stock,
):
    """Severity leads, then recency.

    Ordering purely by time would put a minute-old warning above an hour-old
    stockout, and the top of a triage list has to be the worst thing rather
    than the newest thing.
    """
    other = make_stock(make_product(company, sku="ALT-002"), make_warehouse(company), 0)
    service = AlertService(db_session)

    # The warning is created LAST, so recency alone would float it to the top.
    service.open_alert(
        company_id=company.id,
        alert_type=TYPE_OUT_OF_STOCK,
        severity="critical",
        subject_type="inventory",
        subject_id=other.id,
        title="Out of stock",
        detail={},
    )
    service.open_alert(
        company_id=company.id,
        alert_type=TYPE_LOW_STOCK,
        severity="warning",
        subject_type="inventory",
        subject_id=stock.id,
        title="Low stock",
        detail={},
    )
    db_session.commit()

    data = authenticated_client.get("/api/v1/alerts/").json()["data"]

    assert [a["severity"] for a in data] == ["critical", "warning"]


def test_alerts_are_scoped_to_the_callers_company(
    authenticated_client, db_session, other_company
):
    AlertService(db_session).open_alert(
        company_id=other_company.id,
        alert_type=TYPE_LOW_STOCK,
        severity="warning",
        subject_type="inventory",
        subject_id=uuid.uuid4(),
        title="Someone else's problem",
        detail={},
    )
    db_session.commit()

    body = authenticated_client.get("/api/v1/alerts/?status=all").json()

    assert all(a["title"] != "Someone else's problem" for a in body["data"])
