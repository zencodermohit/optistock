from datetime import datetime, timedelta, timezone

from app.modules.inventory.models import InventoryMovement


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


def _record(db_session, inventory, days_ago, change, after):
    """Backdate a ledger entry, so a trace has history to reconstruct."""
    db_session.add(
        InventoryMovement(
            inventory_id=inventory.id,
            movement_type="sale",
            quantity_change=change,
            quantity_after=after,
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        )
    )
    db_session.commit()


def test_traces_reconstruct_closing_balances_backwards(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    """The series must walk back from today's quantity through the ledger.

    Each entry is that day's CLOSING balance, so a movement lowers the day it
    happened on, not the day after. Stock is 100 today with five sold yesterday
    and ten the day before: yesterday closed at 100, the day before closed at
    105, and everything earlier sat at 115.
    """
    warehouse = make_warehouse(company)
    product = make_product(company)
    inventory = make_stock(product, warehouse, quantity=100)
    _record(db_session, inventory, days_ago=2, change=-10, after=105)
    _record(db_session, inventory, days_ago=1, change=-5, after=100)

    response = authenticated_client.get("/api/v1/inventory/traces?days=7")
    assert response.status_code == 200

    series = response.json()["traces"][str(inventory.id)]
    assert len(series) == 7
    # Newest last: today, yesterday, the day before, then flat history.
    assert series[-1] == 100
    assert series[-2] == 100
    assert series[-3] == 105
    assert series[0] == 115


def test_traces_cover_lines_with_no_recent_movement(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    """A line nothing has touched is flat, not missing.

    Dropping it would leave a hole in the table where every other row has a
    sparkline, which reads as a loading failure rather than as a quiet product.
    """
    warehouse = make_warehouse(company)
    product = make_product(company)
    inventory = make_stock(product, warehouse, quantity=42)

    response = authenticated_client.get("/api/v1/inventory/traces?days=10")

    series = response.json()["traces"][str(inventory.id)]
    assert series == [42] * 10


def test_traces_exclude_other_tenants(
    authenticated_client,
    other_company,
    make_warehouse,
    make_product,
    make_stock,
):
    """The join touches two tenant-owned tables, so both are scoped."""
    warehouse = make_warehouse(other_company)
    product = make_product(other_company)
    inventory = make_stock(product, warehouse, quantity=77)

    response = authenticated_client.get("/api/v1/inventory/traces")

    assert str(inventory.id) not in response.json()["traces"]
