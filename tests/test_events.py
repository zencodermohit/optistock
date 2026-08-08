"""The event backbone: outbox writes, threshold crossings, and the relay."""

import json

from app.modules.events import types as event_types
from app.modules.events.models import EventOutbox
from app.workers.relay import publish_batch


class FakeRedis:
    """Records XADDs instead of performing them.

    The relay takes its client as an argument precisely so this can exist: the
    logic worth testing is which rows get claimed and when they are marked, and
    none of that needs a broker running.
    """

    def __init__(self):
        self.entries = []

    def xadd(self, key, fields, **kwargs):
        self.entries.append((key, fields))
        return f"0-{len(self.entries)}"


def _events(db_session, company, event_type=None):
    query = db_session.query(EventOutbox).filter(EventOutbox.company_id == company.id)
    if event_type:
        query = query.filter(EventOutbox.event_type == event_type)
    return query.order_by(EventOutbox.sequence).all()


# ---------------------------------------------------------------------------
# Producing
# ---------------------------------------------------------------------------
def test_stock_adjustment_writes_an_outbox_event(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company, sku="EVT-001")
    make_stock(product, warehouse, quantity=50)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -5,
            "reason": "cycle count",
        },
    )
    assert response.status_code == 200

    moved = _events(db_session, company, event_types.STOCK_MOVED)
    assert len(moved) == 1
    # The payload has to stand on its own. A consumer that must query the
    # database to learn which SKU moved is coupled to the producer's schema.
    assert moved[0].payload["sku"] == "EVT-001"
    assert moved[0].payload["quantity_change"] == -5
    assert moved[0].payload["quantity_after"] == 45
    assert moved[0].published_at is None


def test_failed_adjustment_leaves_no_event(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    """The whole reason the event is a database row and not a publish call.

    Deducting more than exists is rejected and rolled back. If the event had
    been pushed to a broker first, the rollback could not recall it and every
    consumer would act on a stock movement that never happened.
    """
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=3)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -10,
            "reason": "should fail",
        },
    )
    assert response.status_code == 400
    assert _events(db_session, company) == []


def test_threshold_event_fires_on_the_crossing_only(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    """Crossing below the reorder point is an event; staying below is not.

    Emitting on every movement while low would mean a slow-moving product
    generated an alert per sale for a week, and an alert that arrives fifty
    times is an alert nobody reads.
    """
    warehouse = make_warehouse(company)
    product = make_product(company)
    inventory = make_stock(product, warehouse, quantity=100)
    inventory.reorder_point = 20
    db_session.commit()

    def adjust(change):
        return authenticated_client.post(
            "/api/v1/inventory/adjust",
            json={
                "product_id": str(product.id),
                "warehouse_id": str(warehouse.id),
                "quantity_change": change,
                "reason": "sale deduction",
            },
        )

    assert adjust(-70).status_code == 200  # 100 -> 30, still above
    assert _events(db_session, company, event_types.STOCK_BELOW_REORDER_POINT) == []

    assert adjust(-15).status_code == 200  # 30 -> 15, crosses
    crossed = _events(db_session, company, event_types.STOCK_BELOW_REORDER_POINT)
    assert len(crossed) == 1
    assert crossed[0].payload["quantity"] == 15

    assert adjust(-5).status_code == 200  # 15 -> 10, still below, no new event
    assert len(_events(db_session, company, event_types.STOCK_BELOW_REORDER_POINT)) == 1


def test_reaching_zero_reports_depletion_not_just_low_stock(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    inventory = make_stock(product, warehouse, quantity=8)
    inventory.reorder_point = 5
    db_session.commit()

    authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -8,
            "reason": "sold out",
        },
    )

    assert len(_events(db_session, company, event_types.STOCK_DEPLETED)) == 1
    # Out of stock supersedes low stock. Sending both would have the UI show a
    # warning and a critical for one physical fact.
    assert _events(db_session, company, event_types.STOCK_BELOW_REORDER_POINT) == []


# ---------------------------------------------------------------------------
# Relaying
# ---------------------------------------------------------------------------
def test_relay_publishes_then_marks_published(
    db_session, company, make_warehouse, make_product, make_stock, authenticated_client
):
    warehouse = make_warehouse(company)
    product = make_product(company, sku="RLY-001")
    make_stock(product, warehouse, quantity=10)
    authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -1,
            "reason": "relay test",
        },
    )

    fake = FakeRedis()
    assert publish_batch(db_session, fake) == 1

    _key, fields = fake.entries[0]
    assert fields["event_type"] == event_types.STOCK_MOVED
    assert fields["company_id"] == str(company.id)
    # Nested payload travels as one JSON field, so adding a key to a payload is
    # not a change to the transport's shape.
    assert json.loads(fields["payload"])["sku"] == "RLY-001"

    assert _events(db_session, company)[0].published_at is not None


def test_relay_does_not_republish_what_it_already_sent(
    db_session, company, make_warehouse, make_product, make_stock, authenticated_client
):
    """published_at is the whole state machine; a second pass must find nothing."""
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=10)
    authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -1,
            "reason": "once only",
        },
    )

    first = FakeRedis()
    assert publish_batch(db_session, first) >= 1
    second = FakeRedis()
    assert publish_batch(db_session, second) == 0
    assert second.entries == []


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def test_event_feed_is_scoped_to_the_callers_company(
    authenticated_client,
    db_session,
    other_company,
    make_warehouse,
    make_product,
    make_stock,
):
    warehouse = make_warehouse(other_company)
    product = make_product(other_company, sku="OTHER-001")
    make_stock(product, warehouse, quantity=10)

    from app.modules.events.publisher import record_event

    record_event(
        db_session,
        company_id=other_company.id,
        event_type=event_types.STOCK_MOVED,
        aggregate_type=event_types.AGGREGATE_INVENTORY,
        aggregate_id=product.id,
        payload={"sku": "OTHER-001"},
    )
    db_session.commit()

    response = authenticated_client.get("/api/v1/events/")
    assert response.status_code == 200
    skus = [e["payload"].get("sku") for e in response.json()["data"]]
    assert "OTHER-001" not in skus


def test_outbox_health_reports_the_backlog(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=10)
    authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -1,
            "reason": "backlog",
        },
    )

    body = authenticated_client.get("/api/v1/events/health").json()
    assert body["unpublished"] >= 1
    # An unpublished event always has an age; a backlog with no age would mean
    # the query lost the timestamp and the number is not measuring lag.
    assert body["oldest_unpublished_age_seconds"] is not None
