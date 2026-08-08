def test_get_inventory_unauthorized(client):
    """If we use the normal client (no token), it should fail with 401."""
    response = client.get("/api/v1/inventory/")
    assert response.status_code == 401


def test_get_inventory_authorized(authenticated_client):
    """If we use the authenticated client, it should pass the RBAC check."""
    response = authenticated_client.get("/api/v1/inventory/")

    # 200 means the token was accepted.
    # It might return an empty list if DB is empty, which is fine!
    assert response.status_code == 200

    data = response.json()
    assert "total" in data
    assert "data" in data
