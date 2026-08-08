"""The hardware seam: POST /ingest/scan."""

from app.modules.events import types as event_types
from app.modules.events.models import EventOutbox
from app.modules.inventory.models import Inventory


def _scan(client, sku, warehouse, direction="out", quantity=1, reference=None):
    body = {
        "sku": sku,
        "warehouse_id": str(warehouse.id),
        "direction": direction,
        "quantity": quantity,
        "device_id": "gun-01",
    }
    if reference:
        body["scan_reference"] = reference
    return client.post("/api/v1/ingest/scan", json=body)


def test_scan_moves_stock_and_reports_the_new_level(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company, sku="SCN-001")
    make_stock(product, warehouse, quantity=40)

    response = _scan(authenticated_client, "SCN-001", warehouse, "out", 3)

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "accepted": True,
        "sku": "SCN-001",
        "quantity_after": 37,
        "duplicate": False,
    }


def test_scan_in_adds_stock(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company, sku="SCN-002")
    make_stock(product, warehouse, quantity=5)

    response = _scan(authenticated_client, "SCN-002", warehouse, "in", 12)

    assert response.json()["quantity_after"] == 17


def test_repeating_a_scan_reference_is_a_no_op(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    """A retried scan must not deduct twice.

    Radios drop acknowledgements and triggers get held a beat too long. Without
    idempotency the device has to decide whether its own retry was safe, which
    it cannot know -- so the server decides, and answers the retry with the same
    result rather than an error.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="SCN-003")
    make_stock(product, warehouse, quantity=20)

    first = _scan(authenticated_client, "SCN-003", warehouse, "out", 4, reference="t-1")
    second = _scan(
        authenticated_client, "SCN-003", warehouse, "out", 4, reference="t-1"
    )

    assert first.json()["quantity_after"] == 16
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["quantity_after"] == 16
    assert second.json()["duplicate"] is True

    inventory = (
        db_session.query(Inventory).filter(Inventory.product_id == product.id).one()
    )
    assert inventory.quantity == 16


def test_scan_emits_both_the_movement_and_the_scan(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    """Two events, because they are two different facts.

    `stock.moved` says the number changed. `scan.recorded` says a device on a
    floor saw a physical object. Only one of those survives a later correction
    of the stock level.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="SCN-004")
    make_stock(product, warehouse, quantity=10)

    _scan(authenticated_client, "SCN-004", warehouse, "out", 1, reference="t-2")

    types = [
        e.event_type
        for e in db_session.query(EventOutbox)
        .filter(EventOutbox.company_id == company.id)
        .all()
    ]
    assert event_types.STOCK_MOVED in types
    assert event_types.SCAN_RECORDED in types


def test_unknown_sku_is_rejected_as_unprocessable(
    authenticated_client, company, make_warehouse
):
    """422, not 404. The URL was right; the barcode names nothing we stock."""
    warehouse = make_warehouse(company)

    response = _scan(authenticated_client, "NOT-A-REAL-SKU", warehouse)

    assert response.status_code == 422
    assert "NOT-A-REAL-SKU" in response.json()["detail"]


def test_scan_cannot_reach_another_companys_sku(
    authenticated_client, other_company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(other_company)
    product = make_product(other_company, sku="THEIRS-001")
    make_stock(product, warehouse, quantity=99)

    response = _scan(authenticated_client, "THEIRS-001", warehouse)

    # Indistinguishable from a SKU that does not exist, which is the point:
    # a different status code here would confirm the other tenant stocks it.
    assert response.status_code == 422


def test_scan_cannot_drive_stock_negative(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company, sku="SCN-005")
    make_stock(product, warehouse, quantity=2)

    response = _scan(authenticated_client, "SCN-005", warehouse, "out", 5)

    assert response.status_code == 400


def test_scan_requires_authentication(client, company, make_warehouse):
    """A device on a warehouse floor is not trusted more than a browser."""
    warehouse = make_warehouse(company)

    response = _scan(client, "ANY", warehouse)

    assert response.status_code == 401
