"""The read models behind the screens that had no screen.

Four modules shipped an API long before a page, and all four returned foreign
keys. These tests cover the difference: names resolved, derived figures
computed once on the server, and the tenant boundary held in every one.
"""

import pytest

from app.modules.analytics.readmodels import (
    audit_trail,
    reconciliation_board,
    supplier_scorecard,
    transfer_board,
)
from app.modules.purchase_orders.schemas import POItemBase, PurchaseOrderCreate
from app.modules.purchase_orders.service import PurchaseOrderService
from app.modules.reconciliation.models import Reconciliation, ReconciliationItem
from app.modules.suppliers.models import Supplier
from app.modules.transfers.models import Transfer, TransferItem


@pytest.fixture
def supplier(db_session, company):
    record = Supplier(company_id=company.id, name="Acme Supply", is_active=True)
    db_session.add(record)
    db_session.flush()
    return record


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
def test_delivery_rate_is_counted_from_orders_not_asserted(
    db_session, company, supplier, make_product, make_warehouse
):
    """The stored reliability_score is a claim; this is the evidence."""
    product = make_product(company, sku="SUP-1")
    warehouse = make_warehouse(company)
    service = PurchaseOrderService(db_session)

    orders = [
        service.create_po(
            PurchaseOrderCreate(
                supplier_id=supplier.id,
                destination_warehouse_id=warehouse.id,
                items=[POItemBase(product_id=product.id, quantity=1, unit_price=10.0)],
            ),
            company.id,
        )
        for _ in range(4)
    ]
    db_session.commit()

    # One of four actually arrives.
    service.mark_po_as_delivered(orders[0].id, company.id)
    db_session.commit()

    row = next(
        r for r in supplier_scorecard(db_session, company.id) if r["name"] == "Acme Supply"
    )

    assert row["orders"] == 4
    assert row["delivered"] == 1
    assert row["delivery_rate"] == 0.25
    assert row["spend"] == 40.0


def test_a_supplier_with_no_orders_has_no_delivery_rate(db_session, company, supplier):
    """Null, not zero. Showing 0% would libel a supplier for being new."""
    db_session.commit()

    row = supplier_scorecard(db_session, company.id)[0]

    assert row["orders"] == 0
    assert row["delivery_rate"] is None


def test_supplier_scorecard_is_scoped(db_session, company, other_company):
    db_session.add(Supplier(company_id=company.id, name="Mine", is_active=True))
    db_session.add(Supplier(company_id=other_company.id, name="Theirs", is_active=True))
    db_session.commit()

    assert [r["name"] for r in supplier_scorecard(db_session, company.id)] == ["Mine"]


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------
def test_the_transfer_board_names_both_ends(
    db_session, company, make_warehouse, make_product
):
    source = make_warehouse(company, name="Source Depot")
    destination = make_warehouse(company, name="Destination Depot")
    product = make_product(company, sku="TRAN-1", name="Transferred widget")

    transfer = Transfer(
        company_id=company.id,
        source_warehouse_id=source.id,
        destination_warehouse_id=destination.id,
        status="pending",
    )
    db_session.add(transfer)
    db_session.flush()
    db_session.add(
        TransferItem(transfer_id=transfer.id, product_id=product.id, quantity=9)
    )
    db_session.commit()

    row = transfer_board(db_session, company.id)[0]

    assert row["source_name"] == "Source Depot"
    assert row["destination_name"] == "Destination Depot"
    assert row["items"][0]["sku"] == "TRAN-1"
    assert row["units"] == 9


def test_transfer_board_is_scoped(
    db_session, company, other_company, make_warehouse, make_product
):
    for owner in (company, other_company):
        db_session.add(
            Transfer(
                company_id=owner.id,
                source_warehouse_id=make_warehouse(owner).id,
                destination_warehouse_id=make_warehouse(owner).id,
                status="pending",
            )
        )
    db_session.commit()

    assert len(transfer_board(db_session, company.id)) == 1


# ---------------------------------------------------------------------------
# Reconciliations
# ---------------------------------------------------------------------------
def test_short_and_over_are_kept_apart_rather_than_netted(
    db_session, company, make_warehouse, make_product
):
    """40 short and 40 over is two errors, not a clean count.

    Netting them to zero would report a perfect count and hide both.
    """
    warehouse = make_warehouse(company, name="Counted Depot")
    short = make_product(company, sku="SHORT-1")
    over = make_product(company, sku="OVER-1")
    exact = make_product(company, sku="EXACT-1")

    recon = Reconciliation(
        company_id=company.id, warehouse_id=warehouse.id, status="pending"
    )
    db_session.add(recon)
    db_session.flush()
    for product, expected, actual in (
        (short, 100, 60),
        (over, 100, 140),
        (exact, 50, 50),
    ):
        db_session.add(
            ReconciliationItem(
                reconciliation_id=recon.id,
                product_id=product.id,
                expected_quantity=expected,
                actual_quantity=actual,
            )
        )
    db_session.commit()

    row = reconciliation_board(db_session, company.id)[0]

    assert row["warehouse_name"] == "Counted Depot"
    assert row["counted"] == 3
    assert row["discrepancies"] == 2
    assert row["units_short"] == 40
    assert row["units_over"] == 40
    variances = {line["sku"]: line["variance"] for line in row["items"]}
    assert variances == {"SHORT-1": -40, "OVER-1": 40, "EXACT-1": 0}


def test_reconciliation_board_is_scoped(
    db_session, company, other_company, make_warehouse
):
    for owner in (company, other_company):
        db_session.add(
            Reconciliation(
                company_id=owner.id,
                warehouse_id=make_warehouse(owner).id,
                status="pending",
            )
        )
    db_session.commit()

    assert len(reconciliation_board(db_session, company.id)) == 1


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def test_the_audit_trail_resolves_the_actor_to_a_person(
    authenticated_client, db_session, company, admin_user
):
    """The row keeps user_id, which is right. A screen needs an email.

    Driven through the API because that is the only path that binds an actor to
    the session -- a background job writing directly is deliberately unaudited,
    and there is a separate test asserting it does not crash for the lack.
    """
    authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "AUDITED-1",
            "name": "Audited widget",
            "category": "test",
            "unit_cost": 5,
            "selling_price": 9,
        },
    )

    trail = audit_trail(db_session, company.id)

    assert trail["total"] >= 1
    assert trail["data"][0]["actor"] == admin_user.email
    # The filter offers what exists rather than a hardcoded list.
    assert "products" in trail["entities"]
    assert "CREATE" in trail["actions"]


def test_the_audit_trail_is_scoped(
    authenticated_client, db_session, company, other_company, other_auth_headers
):
    payload = {
        "name": "Scoped widget",
        "category": "test",
        "unit_cost": 5,
        "selling_price": 9,
    }
    authenticated_client.post("/api/v1/products/", json={**payload, "sku": "MINE-AUD"})
    authenticated_client.post(
        "/api/v1/products/",
        json={**payload, "sku": "THEIRS-AUD"},
        headers=other_auth_headers,
    )

    mine = {row["entity_id"] for row in audit_trail(db_session, company.id)["data"]}
    theirs = {
        row["entity_id"] for row in audit_trail(db_session, other_company.id)["data"]
    }

    assert mine and theirs
    assert mine.isdisjoint(theirs)


def test_audit_trail_is_reachable_over_http(authenticated_client):
    response = authenticated_client.get("/api/v1/audit/trail")

    assert response.status_code == 200
    body = response.json()
    assert "data" in body and "entities" in body


def test_the_boards_are_routed_above_their_id_lookups(authenticated_client):
    """Below /{id} these literals are read as UUIDs and rejected."""
    for path in (
        "/api/v1/suppliers/scorecard",
        "/api/v1/transfers/board",
        "/api/v1/reconciliations/board",
    ):
        assert authenticated_client.get(path).status_code == 200, path
