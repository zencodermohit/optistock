"""Sales endpoint tests.

Transaction and rollback behaviour lives in test_transaction_integrity.py; this
file covers the endpoint surface itself.
"""


def test_list_sales_requires_authentication(client):
    assert client.get("/api/v1/sales/").status_code == 401


def test_list_sales_returns_a_paginated_envelope(authenticated_client):
    response = authenticated_client.get("/api/v1/sales/")

    assert response.status_code == 200
    body = response.json()
    assert body == {"total": 0, "skip": 0, "limit": 50, "data": []}


def test_create_sale_rejects_malformed_payload(authenticated_client):
    assert (
        authenticated_client.post("/api/v1/sales/", json={"bad": "data"}).status_code
        == 422
    )


def test_create_sale_requires_at_least_one_item(
    authenticated_client, company, make_customer, make_warehouse
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [],
        },
    )
    assert response.status_code == 422


def test_create_sale_deducts_stock(
    authenticated_client,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=100)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 30, "unit_price": 9.99}
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "completed"
    assert body["total_amount"] == 299.70

    inventory = authenticated_client.get("/api/v1/inventory/")
    quantities = {i["product_id"]: i["quantity"] for i in inventory.json()["data"]}
    assert quantities[str(product.id)] == 70


def test_analyst_cannot_create_sales(
    client, analyst_headers, company, make_customer, make_warehouse, make_product
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)

    response = client.post(
        "/api/v1/sales/",
        headers=analyst_headers,
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 1, "unit_price": 5.0}
            ],
        },
    )
    assert response.status_code == 403
