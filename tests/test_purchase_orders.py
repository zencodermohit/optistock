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
