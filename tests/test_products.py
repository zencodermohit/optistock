"""Product endpoint tests.

Rewritten to exercise the real service and database rather than patching
``ProductService``. Mocking the service meant the previous tests could not
detect a broken query, a broken tenant filter, or a shadowed route.
"""


def test_list_products_requires_authentication(client):
    assert client.get("/api/v1/products/").status_code == 401


def test_list_products_returns_only_this_tenants_rows(
    authenticated_client, company, other_company, make_product
):
    make_product(company, name="Mine")
    make_product(other_company, name="Theirs")

    response = authenticated_client.get("/api/v1/products/")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [p["name"] for p in body["data"]] == ["Mine"]


def test_create_product(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-CREATE-1",
            "name": "Blue Mug",
            "category": "kitchen",
            "unit_cost": 4.50,
            "selling_price": 12.00,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["sku"] == "SKU-CREATE-1"
    assert body["status"] == "active"


def test_create_product_rejects_empty_payload(authenticated_client):
    assert authenticated_client.post("/api/v1/products/", json={}).status_code == 422


def test_create_product_rejects_client_supplied_company_id(authenticated_client):
    """Tenant identity must come from the token, never the request body."""
    response = authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-INJECT-1",
            "name": "Injected",
            "unit_cost": 1,
            "selling_price": 2,
            "company_id": "11111111-1111-1111-1111-111111111111",
        },
    )
    assert response.status_code == 422


def test_create_product_rejects_selling_price_below_cost(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-LOSS-1",
            "name": "Loss Leader",
            "unit_cost": 20,
            "selling_price": 5,
        },
    )
    assert response.status_code == 400
    assert "lower than unit cost" in response.json()["detail"]


def test_create_product_rejects_duplicate_sku_within_tenant(
    authenticated_client, company, make_product
):
    make_product(company, sku="SKU-DUPE-1")

    response = authenticated_client.post(
        "/api/v1/products/",
        json={
            "sku": "SKU-DUPE-1",
            "name": "Copycat",
            "unit_cost": 1,
            "selling_price": 2,
        },
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_analyst_cannot_create_products(client, analyst_headers):
    response = client.post(
        "/api/v1/products/",
        headers=analyst_headers,
        json={"sku": "SKU-RBAC-1", "name": "Nope", "unit_cost": 1, "selling_price": 2},
    )
    assert response.status_code == 403


def test_delete_is_a_soft_delete(authenticated_client, company, make_product):
    product = make_product(company)

    response = authenticated_client.delete(f"/api/v1/products/{product.id}")

    assert response.status_code == 200
    assert response.json()["status"] == "archived"


def test_export_csv_is_reachable(authenticated_client, company, make_product):
    """Regression test for route shadowing.

    ``GET /{product_id}`` is declared before ``GET /export-csv``. FastAPI matches
    in declaration order, so the literal path is swallowed by the UUID path
    parameter and never reached unless the specific route is registered first.
    """
    make_product(company, sku="SKU-EXPORT-1", name="Exportable")

    response = authenticated_client.get("/api/v1/products/export-csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "SKU-EXPORT-1" in response.text
