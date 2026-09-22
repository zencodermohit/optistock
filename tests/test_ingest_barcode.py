"""Scanning by the number printed on the article, rather than by our SKU.

The SKU path is what a bench-mounted gun uses: somebody configured it with our
codes. A phone camera has no such luxury -- it reads whatever the manufacturer
printed -- so the endpoint has to resolve an EAN-13 to a product, and the
catalogue has to be teachable when it meets one it does not know.
"""

from app.modules.inventory.models import Inventory
from app.modules.products.models import Product


def _scan_barcode(client, barcode, warehouse, direction="out", quantity=1, reference=None):
    body = {
        "barcode": barcode,
        "warehouse_id": str(warehouse.id),
        "direction": direction,
        "quantity": quantity,
        "device_id": "phone-01",
    }
    if reference:
        body["scan_reference"] = reference
    return client.post("/api/v1/ingest/scan", json=body)


def test_a_barcode_moves_stock_and_answers_with_our_sku(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    """The device speaks EAN; the response speaks SKU.

    Worth asserting explicitly. The client sent no SKU at all, so returning one
    is the endpoint translating the manufacturer's vocabulary into ours, which
    is the entire point of the column.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="BAR-001", barcode="8901058000108")
    make_stock(product, warehouse, quantity=40)

    response = _scan_barcode(authenticated_client, "8901058000108", warehouse, "out", 3)

    assert response.status_code == 200
    assert response.json() == {
        "accepted": True,
        "sku": "BAR-001",
        "quantity_after": 37,
        "duplicate": False,
    }


def test_an_unknown_barcode_says_so_in_a_form_the_client_can_act_on(
    authenticated_client, company, make_warehouse
):
    """Not merely "no", but "no, and here is the one you could link".

    The scanner offers to teach the catalogue when it meets an article nobody
    has mapped yet. It can only do that if this failure is distinguishable from
    every other 422 WITHOUT matching on prose, because prose gets reworded.
    """
    warehouse = make_warehouse(company)

    response = _scan_barcode(authenticated_client, "4006381333931", warehouse)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["reason"] == "unknown_barcode"
    assert detail["barcode"] == "4006381333931"
    assert detail["message"]


def test_a_barcode_belongs_to_one_company_only(
    authenticated_client,
    other_client,
    company,
    other_company,
    make_warehouse,
    make_product,
    make_stock,
):
    """The same tin of paint, stocked by two tenants, is two products.

    A global uniqueness constraint would let whichever tenant scanned it first
    take the barcode away from the other, inside their own catalogue. This is
    the test that would fail if the constraint were ever "simplified".
    """
    ours = make_warehouse(company)
    theirs = make_warehouse(other_company)
    mine = make_product(company, sku="MINE-1", barcode="5000112637922")
    yours = make_product(other_company, sku="YOURS-1", barcode="5000112637922")
    make_stock(mine, ours, quantity=10)
    make_stock(yours, theirs, quantity=99)

    assert _scan_barcode(authenticated_client, "5000112637922", ours).json()["sku"] == (
        "MINE-1"
    )
    assert _scan_barcode(other_client, "5000112637922", theirs).json()["sku"] == (
        "YOURS-1"
    )


def test_sending_both_identifiers_is_refused_rather_than_resolved(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    """Two identifiers that disagree have no safe winner.

    Any precedence rule is a guess about what the operator meant, and the wrong
    guess moves stock on the wrong product without saying anything.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="BOTH-1", barcode="9780201379624")
    make_stock(product, warehouse, quantity=10)

    response = authenticated_client.post(
        "/api/v1/ingest/scan",
        json={
            "sku": "BOTH-1",
            "barcode": "9780201379624",
            "warehouse_id": str(warehouse.id),
            "direction": "out",
            "quantity": 1,
        },
    )

    assert response.status_code == 422


def test_sending_neither_identifier_is_refused(
    authenticated_client, company, make_warehouse
):
    warehouse = make_warehouse(company)

    response = authenticated_client.post(
        "/api/v1/ingest/scan",
        json={
            "warehouse_id": str(warehouse.id),
            "direction": "out",
            "quantity": 1,
        },
    )

    assert response.status_code == 422


def test_the_sku_path_still_works(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    """The gun on the bench must not have been broken by teaching the phone."""
    warehouse = make_warehouse(company)
    product = make_product(company, sku="OLD-WAY-1")
    make_stock(product, warehouse, quantity=8)

    response = authenticated_client.post(
        "/api/v1/ingest/scan",
        json={
            "sku": "OLD-WAY-1",
            "warehouse_id": str(warehouse.id),
            "direction": "out",
            "quantity": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["quantity_after"] == 6


def test_a_repeated_barcode_scan_reference_is_still_a_no_op(
    authenticated_client, company, make_warehouse, make_product, make_stock, db_session
):
    """Idempotency is a property of the scan, not of how it named the product.

    A camera re-reads the same barcode many times a second, so this guard is
    under far more pressure from the phone than it ever was from a gun.
    """
    warehouse = make_warehouse(company)
    product = make_product(company, sku="DUP-1", barcode="0123456789012")
    make_stock(product, warehouse, quantity=20)

    first = _scan_barcode(
        authenticated_client, "0123456789012", warehouse, "out", 5, reference="abc-123"
    )
    second = _scan_barcode(
        authenticated_client, "0123456789012", warehouse, "out", 5, reference="abc-123"
    )

    assert first.json()["quantity_after"] == 15
    assert second.json()["duplicate"] is True
    assert second.json()["quantity_after"] == 15

    stock = (
        db_session.query(Inventory)
        .filter(Inventory.product_id == product.id)
        .one()
    )
    db_session.refresh(stock)
    assert stock.quantity == 15


# --- teaching the catalogue -------------------------------------------------


def test_linking_a_barcode_makes_the_next_scan_work(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    """The whole loop: scan fails, operator links, scan succeeds."""
    warehouse = make_warehouse(company)
    product = make_product(company, sku="LEARN-1")
    make_stock(product, warehouse, quantity=10)

    assert _scan_barcode(authenticated_client, "8712345678905", warehouse).status_code == 422

    linked = authenticated_client.patch(
        f"/api/v1/products/{product.id}/barcode",
        json={"barcode": "8712345678905"},
    )
    assert linked.status_code == 200
    assert linked.json()["barcode"] == "8712345678905"

    again = _scan_barcode(authenticated_client, "8712345678905", warehouse, "out", 2)
    assert again.status_code == 200
    assert again.json()["quantity_after"] == 8


def test_linking_a_barcode_twice_names_the_product_that_has_it(
    authenticated_client, company, make_product
):
    """"Taken" is useless; "taken by Instant Noodles" can be acted on.

    The operator is standing at a shelf. Telling them which row already owns
    the code is the difference between fixing it there and walking back to a
    desk.
    """
    first = make_product(company, sku="OWNS-IT", name="Instant Noodles 70g")
    second = make_product(company, sku="WANTS-IT")

    authenticated_client.patch(
        f"/api/v1/products/{first.id}/barcode", json={"barcode": "8901058000108"}
    )
    clash = authenticated_client.patch(
        f"/api/v1/products/{second.id}/barcode", json={"barcode": "8901058000108"}
    )

    assert clash.status_code == 409
    assert "Instant Noodles 70g" in clash.json()["detail"]
    assert "OWNS-IT" in clash.json()["detail"]


def test_a_barcode_can_be_unlinked(authenticated_client, company, make_product):
    """Scanning the wrong packet onto the wrong row must be recoverable."""
    product = make_product(company, sku="OOPS-1", barcode="5901234123457")

    response = authenticated_client.patch(
        f"/api/v1/products/{product.id}/barcode", json={"barcode": None}
    )

    assert response.status_code == 200
    assert response.json()["barcode"] is None


def test_linking_cannot_reach_another_tenants_product(
    other_client, company, make_product
):
    """A 404, not a 403: the other tenant's catalogue does not exist from here."""
    mine = make_product(company, sku="PRIVATE-1")

    response = other_client.patch(
        f"/api/v1/products/{mine.id}/barcode", json={"barcode": "4006381333931"}
    )

    assert response.status_code == 404


def test_a_barcode_with_whitespace_is_refused(
    authenticated_client, company, make_product
):
    """A scan has no spaces in it. A paste does."""
    product = make_product(company, sku="SPACE-1")

    response = authenticated_client.patch(
        f"/api/v1/products/{product.id}/barcode",
        json={"barcode": "8901 058000108"},
    )

    assert response.status_code == 422


def test_products_that_share_no_barcode_do_not_collide(
    authenticated_client, company, make_product, db_session
):
    """Many nulls under a unique constraint.

    Postgres permits repeated NULLs, which is what makes the constraint usable
    at all: almost every product will never be scanned. If this ever fails,
    the constraint has been written in a way that treats "unmapped" as a value.
    """
    for index in range(5):
        make_product(company, sku=f"NULLS-{index}")

    unmapped = (
        db_session.query(Product)
        .filter(Product.company_id == company.id, Product.barcode.is_(None))
        .count()
    )
    assert unmapped >= 5
