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


def test_get_single_sale_includes_line_items(
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
    make_stock(product, warehouse, quantity=50)

    created = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 3, "unit_price": 12.5}
            ],
        },
    )
    assert created.status_code == 201

    detail = authenticated_client.get(f"/api/v1/sales/{created.json()['id']}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["total_amount"] == 37.5
    assert len(body["items"]) == 1
    assert body["items"][0]["quantity"] == 3


def test_sale_list_omits_line_items(
    authenticated_client,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    """The list representation is deliberately lighter than the detail one —
    a page of 50 sales should not drag every line item across the wire."""
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=50)

    authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 1, "unit_price": 5.0}
            ],
        },
    )

    row = authenticated_client.get("/api/v1/sales/").json()["data"][0]
    assert "items" not in row


def test_cannot_read_another_tenants_sale(
    authenticated_client,
    other_client,
    other_company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    customer = make_customer(other_company)
    warehouse = make_warehouse(other_company)
    product = make_product(other_company)
    make_stock(product, warehouse, quantity=10)

    foreign = other_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 1, "unit_price": 5.0}
            ],
        },
    )
    assert foreign.status_code == 201

    assert (
        authenticated_client.get(f"/api/v1/sales/{foreign.json()['id']}").status_code
        == 404
    )


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


# ---------------------------------------------------------------------------
# The ledger read model
# ---------------------------------------------------------------------------
def test_the_ledger_joins_names_and_counts_units(
    db_session, company, make_customer, make_warehouse, make_product, make_stock
):
    """SaleResponse returns UUIDs; a page rendering those at a person is not a
    page. Units come from a grouped query rather than one per row."""
    from app.modules.sales.schemas import SaleCreate, SaleItemCreate
    from app.modules.sales.service import SaleService

    customer = make_customer(company, name="Ledger Buyer")
    warehouse = make_warehouse(company, name="Ledger Depot")
    product = make_product(company, sku="LEDG-1")
    other = make_product(company, sku="LEDG-2")
    make_stock(product, warehouse, quantity=100)
    make_stock(other, warehouse, quantity=100)

    SaleService(db_session).create_sale(
        SaleCreate(
            customer_id=customer.id,
            source_warehouse_id=warehouse.id,
            items=[
                SaleItemCreate(product_id=product.id, quantity=3, unit_price=10.0),
                SaleItemCreate(product_id=other.id, quantity=4, unit_price=5.0),
            ],
        ),
        company.id,
    )
    db_session.commit()

    rows, total, summary = SaleService(db_session).ledger(company.id)

    assert total == 1
    row = rows[0]
    assert row["customer_name"] == "Ledger Buyer"
    assert row["warehouse_name"] == "Ledger Depot"
    assert row["units"] == 7
    assert row["lines"] == 2
    assert row["total_amount"] == 50.0
    # The footer totals what is on screen, so a reader can check it against the
    # rows in front of them.
    assert summary == {"revenue": 50.0, "units": 7, "orders": 1}


def test_the_ledger_is_scoped_to_the_company(
    db_session,
    company,
    other_company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    from app.modules.sales.schemas import SaleCreate, SaleItemCreate
    from app.modules.sales.service import SaleService

    for owner, name in ((company, "Mine"), (other_company, "Theirs")):
        customer = make_customer(owner, name=name)
        warehouse = make_warehouse(owner)
        product = make_product(owner)
        make_stock(product, warehouse, quantity=50)
        SaleService(db_session).create_sale(
            SaleCreate(
                customer_id=customer.id,
                source_warehouse_id=warehouse.id,
                items=[
                    SaleItemCreate(product_id=product.id, quantity=1, unit_price=1.0)
                ],
            ),
            owner.id,
        )
    db_session.commit()

    rows, _, _ = SaleService(db_session).ledger(company.id)

    assert [r["customer_name"] for r in rows] == ["Mine"]


def test_ledger_is_routed_above_the_id_lookup(authenticated_client):
    """The router's own comment warns about this: a literal route below
    /{sale_id} is swallowed and rejected as a malformed UUID."""
    response = authenticated_client.get("/api/v1/sales/ledger")

    assert response.status_code == 200
    assert "summary" in response.json()
