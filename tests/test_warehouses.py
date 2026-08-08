"""Warehouse endpoint tests.

The previous version requested a ``db_session`` fixture that did not exist, and
posted ``company_id`` in the request body, which the hardened schemas now reject.
"""


def test_list_warehouses_requires_authentication(client):
    assert client.get("/api/v1/warehouses/").status_code == 401


def test_create_warehouse(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/warehouses/",
        json={
            "name": "Test Warehouse",
            "location_code": "WH-CREATE-1",
            "capacity_units": 1000,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Test Warehouse"
    assert body["is_active"] is True


def test_create_warehouse_rejects_client_supplied_company_id(authenticated_client):
    """WarehouseCreate sets extra="forbid" so a caller cannot pick their tenant."""
    response = authenticated_client.post(
        "/api/v1/warehouses/",
        json={
            "name": "Sneaky Warehouse",
            "location_code": "WH-INJECT-1",
            "capacity_units": 500,
            "company_id": "12345678-1234-5678-1234-567812345678",
        },
    )
    assert response.status_code == 422


def test_create_warehouse_rejects_non_positive_capacity(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/warehouses/",
        json={"name": "Zero Cap", "location_code": "WH-ZERO-1", "capacity_units": 0},
    )
    assert response.status_code == 422


def test_list_warehouses_is_scoped_to_the_tenant(
    authenticated_client, company, other_company, make_warehouse
):
    make_warehouse(company, name="Mine")
    make_warehouse(other_company, name="Theirs")

    response = authenticated_client.get("/api/v1/warehouses/")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert [w["name"] for w in body["data"]] == ["Mine"]


def test_analyst_cannot_create_warehouses(client, analyst_headers):
    response = client.post(
        "/api/v1/warehouses/",
        headers=analyst_headers,
        json={"name": "Nope", "location_code": "WH-RBAC-1", "capacity_units": 10},
    )
    assert response.status_code == 403
