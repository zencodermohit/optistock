def test_health_check_returns_200(client):
    """
    Test that the /health endpoint returns 200 OK
    and successfully pings the database.
    """
    response = client.get("/health")

    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "ok"
    assert data["database"] == "connected"
    assert "version" in data
