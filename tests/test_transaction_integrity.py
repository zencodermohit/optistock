"""Transaction and rollback guarantees for the inventory ledger.

These are the project's headline claims — "ACID-compliant transactions",
"bulletproof inventory mechanics preventing ghost stock" — and until now nothing
verified them. A regression here would not surface as a crash; it would surface
months later as a physical stock count that disagrees with the database.
"""

import pytest
from sqlalchemy import func, text
from sqlalchemy.exc import IntegrityError

from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.sales.models import Sale, SaleItem


def _quantity(db_session, product, warehouse) -> int:
    db_session.expire_all()
    return (
        db_session.query(Inventory.quantity)
        .filter(
            Inventory.product_id == product.id,
            Inventory.warehouse_id == warehouse.id,
        )
        .scalar()
    )


def test_sale_is_rejected_when_stock_is_insufficient(
    authenticated_client,
    db_session,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=5)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 10, "unit_price": 3.0}
            ],
        },
    )

    assert response.status_code == 400
    assert "Only 5 available" in response.json()["detail"]
    assert _quantity(db_session, product, warehouse) == 5
    assert db_session.query(func.count(Sale.id)).scalar() == 0


def test_partial_sale_failure_rolls_back_earlier_deductions(
    authenticated_client,
    db_session,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    """The single most important test in this suite.

    A two-line sale where the SECOND line has insufficient stock. The first line
    is deducted before the failure is discovered, so if the transaction boundary
    is ever broken, product A silently loses 10 units for a sale that never
    happened. That is ghost stock, and it is invisible without this test.
    """
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    plentiful = make_product(company, name="Plentiful")
    scarce = make_product(company, name="Scarce")
    make_stock(plentiful, warehouse, quantity=100)
    make_stock(scarce, warehouse, quantity=1)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(plentiful.id), "quantity": 10, "unit_price": 5.0},
                {"product_id": str(scarce.id), "quantity": 5, "unit_price": 5.0},
            ],
        },
    )

    assert response.status_code == 400

    # The whole transaction must be undone — not just the line that failed.
    assert _quantity(db_session, plentiful, warehouse) == 100
    assert _quantity(db_session, scarce, warehouse) == 1
    assert db_session.query(func.count(Sale.id)).scalar() == 0
    assert db_session.query(func.count(SaleItem.id)).scalar() == 0
    assert db_session.query(func.count(InventoryMovement.id)).scalar() == 0


def test_successful_sale_writes_the_movement_ledger(
    authenticated_client,
    db_session,
    company,
    make_customer,
    make_warehouse,
    make_product,
    make_stock,
):
    """Every stock change must leave an audit trail in the immutable ledger."""
    customer = make_customer(company)
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=50)

    response = authenticated_client.post(
        "/api/v1/sales/",
        json={
            "customer_id": str(customer.id),
            "source_warehouse_id": str(warehouse.id),
            "items": [
                {"product_id": str(product.id), "quantity": 20, "unit_price": 7.5}
            ],
        },
    )
    assert response.status_code == 201
    sale_id = response.json()["id"]

    movements = db_session.query(InventoryMovement).all()
    assert len(movements) == 1

    movement = movements[0]
    assert movement.movement_type == "sale"
    assert movement.quantity_change == -20
    assert movement.quantity_after == 30
    assert movement.reference_id == sale_id


def test_manual_adjustment_cannot_drive_stock_negative(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=3)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -10,
            "reason": "attempted over-deduction",
        },
    )

    assert response.status_code == 400
    assert _quantity(db_session, product, warehouse) == 3
    assert db_session.query(func.count(InventoryMovement.id)).scalar() == 0


def test_manual_adjustment_records_its_reason(
    authenticated_client, db_session, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=10)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": -4,
            "reason": "damaged in transit",
        },
    )

    assert response.status_code == 200
    assert response.json()["quantity"] == 6

    movement = db_session.query(InventoryMovement).one()
    assert movement.movement_type == "manual_adjustment"
    assert "damaged in transit" in movement.reference_id


def test_database_itself_refuses_negative_stock(
    db_session, company, make_warehouse, make_product, make_stock
):
    """Defence in depth: the CHECK constraint must exist in the DATABASE.

    Inventory.quantity declares CheckConstraint("quantity >= 0") on the model,
    but a model-only declaration protects nothing — it has to be in a migration.
    This test bypasses the service layer entirely and writes raw SQL, so it fails
    unless Postgres is enforcing the rule independently of application code.
    """
    warehouse = make_warehouse(company)
    product = make_product(company)
    inventory = make_stock(product, warehouse, quantity=10)

    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE inventory SET quantity = -5 WHERE id = :id"),
            {"id": inventory.id},
        )
        db_session.flush()


def test_zero_quantity_adjustment_is_rejected(
    authenticated_client, company, make_warehouse, make_product, make_stock
):
    warehouse = make_warehouse(company)
    product = make_product(company)
    make_stock(product, warehouse, quantity=10)

    response = authenticated_client.post(
        "/api/v1/inventory/adjust",
        json={
            "product_id": str(product.id),
            "warehouse_id": str(warehouse.id),
            "quantity_change": 0,
            "reason": "pointless adjustment",
        },
    )
    assert response.status_code == 400
