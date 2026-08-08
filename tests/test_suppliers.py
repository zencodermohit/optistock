"""Supplier endpoint tests."""


def test_list_suppliers_requires_authentication(client):
    assert client.get("/api/v1/suppliers/").status_code == 401


def test_create_supplier(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/suppliers/",
        json={"name": "Test Supplier", "contact_email": "test@supplier.com"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Test Supplier"
    assert body["contact_email"] == "test@supplier.com"
    assert body["is_active"] is True


def test_create_supplier_rejects_malformed_email(authenticated_client):
    response = authenticated_client.post(
        "/api/v1/suppliers/",
        json={"name": "Bad Email Supplier", "contact_email": "not-an-email"},
    )
    assert response.status_code == 422


def test_reliability_score_is_read_only(authenticated_client):
    """Clients must not be able to set their own supplier reliability score."""
    response = authenticated_client.post(
        "/api/v1/suppliers/",
        json={
            "name": "Self Scoring Supplier",
            "contact_email": "score@supplier.com",
            "reliability_score": 99.0,
        },
    )

    # Either the field is rejected outright, or it is ignored — but it must never
    # be accepted at the value the client asked for.
    if response.status_code == 201:
        assert response.json()["reliability_score"] != 99.0
    else:
        assert response.status_code == 422


def test_list_suppliers_is_scoped_to_the_tenant(authenticated_client, other_client):
    authenticated_client.post(
        "/api/v1/suppliers/", json={"name": "Mine", "contact_email": "a@supplier.com"}
    )
    other_client.post(
        "/api/v1/suppliers/", json={"name": "Theirs", "contact_email": "b@supplier.com"}
    )

    response = authenticated_client.get("/api/v1/suppliers/")

    assert response.status_code == 200
    assert [s["name"] for s in response.json()["data"]] == ["Mine"]


def test_analyst_cannot_create_suppliers(client, analyst_headers):
    response = client.post(
        "/api/v1/suppliers/",
        headers=analyst_headers,
        json={"name": "Nope", "contact_email": "nope@supplier.com"},
    )
    assert response.status_code == 403
