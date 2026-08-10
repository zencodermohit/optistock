"""Purchase order endpoint tests.

The previous version posted ``"items": []``, but ``PurchaseOrderCreate`` requires
at least one line item, so it could only ever have returned 422 rather than the
201 it asserted.
"""


def test_list_purchase_orders_requires_authentication(client):
    assert client.get("/api/v1/purchase_orders/").status_code == 401


def test_create_purchase_order(
    authenticated_client, company, make_warehouse, make_product
):
    warehouse = make_warehouse(company)
    product = make_product(company)

    supplier = authenticated_client.post(
        "/api/v1/suppliers/",
        json={"name": "PO Supplier", "contact_email": "po@supplier.com"},
    )
    assert supplier.status_code == 201

    response = authenticated_client.post(
        "/api/v1/purchase_orders/",
        json={
            "supplier_id": supplier.json()["id"],
            "destination_warehouse_id": str(warehouse.id),
            "expected_delivery_date": "2026-12-31",
            "items": [
                {"product_id": str(product.id), "quantity": 25, "unit_price": 4.0}
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "draft"
    assert body["total_amount"] == 100.0
    assert len(body["items"]) == 1


def test_create_purchase_order_requires_at_least_one_item(
    authenticated_client, company, make_warehouse
):
    warehouse = make_warehouse(company)

    supplier = authenticated_client.post(
        "/api/v1/suppliers/",
        json={"name": "Empty PO Supplier", "contact_email": "empty@supplier.com"},
    )

    response = authenticated_client.post(
        "/api/v1/purchase_orders/",
        json={
            "supplier_id": supplier.json()["id"],
            "destination_warehouse_id": str(warehouse.id),
            "expected_delivery_date": "2026-12-31",
            "items": [],
        },
    )
    assert response.status_code == 422


def test_delivering_a_purchase_order_increases_stock(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    """A delivery is the positive counterpart to a sale: it must move the ledger."""
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=5)

    supplier = authenticated_client.post(
        "/api/v1/suppliers/",
        json={"name": "Delivering Supplier", "contact_email": "d@supplier.com"},
    )

    po = authenticated_client.post(
        "/api/v1/purchase_orders/",
        json={
            "supplier_id": supplier.json()["id"],
            "destination_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 30, "unit_price": 2.0}
            ],
        },
    )
    assert po.status_code == 201

    delivered = authenticated_client.patch(
        f"/api/v1/purchase_orders/{po.json()['id']}/deliver"
    )
    assert delivered.status_code == 200
    assert delivered.json()["status"] == "delivered"

    inventory = authenticated_client.get(
        "/api/v1/inventory/", params={"warehouse_id": str(warehouse.id)}
    )
    quantities = {i["product_id"]: i["quantity"] for i in inventory.json()["data"]}
    assert quantities[str(product.id)] == 35


# ---------------------------------------------------------------------------
# The pipeline read model
#
# The Purchase Orders screen renders names and provenance. The ORM response
# returns UUIDs and knows nothing about where an order came from, so this is
# where the difference is made -- and the provenance half is the part that
# exists nowhere else in the schema.
# ---------------------------------------------------------------------------
def test_the_pipeline_joins_the_names_a_screen_needs(
    db_session, company, make_product, make_warehouse
):
    """A page that renders raw UUIDs at a stock controller is not a page."""
    from app.modules.purchase_orders.service import PurchaseOrderService
    from app.modules.purchase_orders.schemas import POItemBase, PurchaseOrderCreate
    from app.modules.suppliers.models import Supplier

    product = make_product(company, sku="PIPE-1", name="Pipeline widget")
    warehouse = make_warehouse(company, name="Pipeline Depot")
    supplier = Supplier(company_id=company.id, name="Pipeline Supply Co", is_active=True)
    db_session.add(supplier)
    db_session.flush()

    PurchaseOrderService(db_session).create_po(
        PurchaseOrderCreate(
            supplier_id=supplier.id,
            destination_warehouse_id=warehouse.id,
            items=[POItemBase(product_id=product.id, quantity=12, unit_price=5.0)],
        ),
        company.id,
    )
    db_session.commit()

    rows = PurchaseOrderService(db_session).pipeline(company.id)

    assert len(rows) == 1
    row = rows[0]
    assert row["supplier_name"] == "Pipeline Supply Co"
    assert row["warehouse_name"] == "Pipeline Depot"
    assert row["items"][0]["sku"] == "PIPE-1"
    assert row["items"][0]["product_name"] == "Pipeline widget"
    assert row["units"] == 12
    assert row["items"][0]["line_total"] == 60.0
    # No proposal behind this one, and the honest answer is null rather than a
    # fabricated "created by a human".
    assert row["origin"] is None


def test_an_approved_proposal_carries_its_provenance_into_the_order(
    db_session, company, make_product, make_warehouse, make_stock, admin_user
):
    """The signature of the screen, asserted.

    An order that began as an assistant proposal says so, and when the approver
    amended the quantity both numbers survive -- that gap is the whole
    human-in-the-loop design, and this is the last place it can be seen.
    """
    from app.modules.assistant.actions import ActionService
    from app.modules.purchase_orders.service import PurchaseOrderService
    from app.modules.suppliers.models import Supplier

    product = make_product(company, sku="PROV-1", name="Provenance widget")
    product.unit_cost = 10
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=2)
    db_session.add(Supplier(company_id=company.id, name="Origin Supply", is_active=True))
    db_session.commit()

    service = ActionService(db_session)
    action, error = service.propose_purchase_order(
        company_id=company.id,
        sku="PROV-1",
        quantity=200,
        rationale="Only 2 left and it sells daily.",
        model="gemini-3.6-flash",
    )
    assert error is None
    service.approve(
        company_id=company.id,
        action_id=action.id,
        user_id=admin_user.id,
        overrides={"quantity": 40},
    )
    db_session.commit()

    row = PurchaseOrderService(db_session).pipeline(company.id)[0]

    assert row["origin"] is not None
    assert row["origin"]["model"] == "gemini-3.6-flash"
    assert row["origin"]["proposed_quantity"] == 200
    assert row["origin"]["executed_quantity"] == 40
    assert row["origin"]["amended"] is True
    assert row["origin"]["rationale"] == "Only 2 left and it sells daily."
    # And the order itself is for what the human signed, not what the model asked.
    assert row["units"] == 40


def test_the_pipeline_is_scoped_to_the_company(
    db_session, company, other_company, make_product, make_warehouse
):
    from app.modules.purchase_orders.service import PurchaseOrderService
    from app.modules.purchase_orders.schemas import POItemBase, PurchaseOrderCreate
    from app.modules.suppliers.models import Supplier

    for owner, sku in ((company, "MINE-PIPE"), (other_company, "THEIRS-PIPE")):
        product = make_product(owner, sku=sku)
        warehouse = make_warehouse(owner)
        supplier = Supplier(company_id=owner.id, name=f"{sku} Supply", is_active=True)
        db_session.add(supplier)
        db_session.flush()
        PurchaseOrderService(db_session).create_po(
            PurchaseOrderCreate(
                supplier_id=supplier.id,
                destination_warehouse_id=warehouse.id,
                items=[POItemBase(product_id=product.id, quantity=1, unit_price=1.0)],
            ),
            owner.id,
        )
    db_session.commit()

    rows = PurchaseOrderService(db_session).pipeline(company.id)

    assert [r["items"][0]["sku"] for r in rows] == ["MINE-PIPE"]


def test_pipeline_is_routed_above_the_id_lookup(authenticated_client):
    """Declared before /{po_id}. Below it, "pipeline" is read as an order id
    and rejected as a malformed UUID."""
    response = authenticated_client.get("/api/v1/purchase_orders/pipeline")

    assert response.status_code == 200
    assert "data" in response.json()
