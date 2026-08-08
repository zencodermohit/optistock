"""Concurrency guarantees for the inventory ledger.

Why this file does not use the shared ``db_session`` fixture
------------------------------------------------------------
Every other test runs inside one transaction that is rolled back at the end.
That is perfect for isolation, but it makes concurrency untestable: row locks
only take effect BETWEEN transactions on separate connections. To prove that
``SELECT ... FOR UPDATE`` actually serialises competing writers, these tests
need real connections doing real commits, so they seed committed data and clean
it up explicitly in a finally block.

The failure being guarded against is the classic lost update:

    A reads qty=1 ─┐
    B reads qty=1 ─┤   both compute 1-1=0
    A writes 0    ─┤   both "succeed"
    B writes 0    ─┘   two units sold, one unit existed

This is invisible in manual testing and appears only under real traffic.
"""

import threading
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.exceptions import OptiStockException
from app.modules.companies.models import Company
from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.inventory.service import InventoryService
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse


@pytest.fixture
def committed_stock(engine):
    """Seed a product/warehouse with committed stock, and tear it down after.

    Yields a callable so each test picks its own starting quantity.
    """
    created = {}

    def _seed(quantity: int):
        session = Session(engine)
        try:
            suffix = uuid.uuid4().hex[:10]
            company = Company(name=f"Concurrency Co {suffix}")
            session.add(company)
            session.flush()

            product = Product(
                company_id=company.id,
                sku=f"SKU-CONC-{suffix}",
                name="Contended Widget",
                unit_cost=1,
                selling_price=2,
                status="active",
            )
            warehouse = Warehouse(
                company_id=company.id,
                name="Contended Warehouse",
                location_code=f"WH-CONC-{suffix}",
                capacity_units=1000,
                is_active=True,
            )
            session.add_all([product, warehouse])
            session.flush()

            session.add(
                Inventory(
                    product_id=product.id,
                    warehouse_id=warehouse.id,
                    quantity=quantity,
                )
            )
            session.commit()

            created.update(
                company_id=company.id, product_id=product.id, warehouse_id=warehouse.id
            )
            return dict(created)
        finally:
            session.close()

    yield _seed

    if created:
        cleanup = Session(engine)
        try:
            cleanup.execute(
                text(
                    "DELETE FROM inventory_movements WHERE inventory_id IN "
                    "(SELECT id FROM inventory WHERE product_id = :p)"
                ),
                {"p": created["product_id"]},
            )
            cleanup.execute(
                text("DELETE FROM inventory WHERE product_id = :p"),
                {"p": created["product_id"]},
            )
            cleanup.execute(
                text("DELETE FROM products WHERE id = :p"), {"p": created["product_id"]}
            )
            cleanup.execute(
                text("DELETE FROM warehouses WHERE id = :w"),
                {"w": created["warehouse_id"]},
            )
            # Stock movements now emit outbox events, which reference the
            # company. These tests commit for real -- that is the point, they
            # exercise row locking across connections -- so unlike every other
            # test here they cannot rely on a rollback to tidy up. Anything
            # holding a reference to the company has to be removed by name, and
            # missing one does not fail quietly: the DELETE below aborts, this
            # whole cleanup rolls back, and the leftovers break the tests that
            # run next.
            cleanup.execute(
                text("DELETE FROM event_outbox WHERE company_id = :c"),
                {"c": created["company_id"]},
            )
            cleanup.execute(
                text("DELETE FROM companies WHERE id = :c"),
                {"c": created["company_id"]},
            )
            cleanup.commit()
        finally:
            cleanup.close()


def _deduct_in_parallel(engine, seeded, workers: int, quantity_each: int):
    """Fire N concurrent deductions released simultaneously by a barrier."""
    barrier = threading.Barrier(workers)
    outcomes = []
    lock = threading.Lock()

    def worker():
        session = Session(engine)
        try:
            service = InventoryService(session)
            # Line everyone up so the reads genuinely overlap.
            barrier.wait(timeout=20)
            service.adjust_inventory(
                product_id=seeded["product_id"],
                warehouse_id=seeded["warehouse_id"],
                company_id=seeded["company_id"],
                quantity_change=-quantity_each,
                movement_type="sale",
                reference_id="concurrency-test",
            )
            session.commit()
            with lock:
                outcomes.append("committed")
        except OptiStockException:
            session.rollback()
            with lock:
                outcomes.append("rejected")
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected
            session.rollback()
            with lock:
                outcomes.append(f"error:{type(exc).__name__}")
        finally:
            session.close()

    threads = [threading.Thread(target=worker) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    return outcomes


def _final_quantity(engine, seeded) -> int:
    session = Session(engine)
    try:
        return (
            session.query(Inventory.quantity)
            .filter(Inventory.product_id == seeded["product_id"])
            .scalar()
        )
    finally:
        session.close()


def test_two_buyers_cannot_both_take_the_last_unit(engine, committed_stock):
    seeded = committed_stock(quantity=1)

    outcomes = _deduct_in_parallel(engine, seeded, workers=2, quantity_each=1)

    assert outcomes.count("committed") == 1, f"expected exactly one winner: {outcomes}"
    assert outcomes.count("rejected") == 1, f"expected exactly one loser: {outcomes}"
    assert _final_quantity(engine, seeded) == 0


def test_stock_never_goes_negative_under_heavy_contention(engine, committed_stock):
    """Ten threads race for five units. Exactly five may win."""
    seeded = committed_stock(quantity=5)

    outcomes = _deduct_in_parallel(engine, seeded, workers=10, quantity_each=1)

    assert outcomes.count("committed") == 5, f"oversold or undersold: {outcomes}"
    assert outcomes.count("rejected") == 5, f"unexpected outcomes: {outcomes}"

    final = _final_quantity(engine, seeded)
    assert final == 0
    assert final >= 0, "stock went negative — row locking is not holding"


def test_every_committed_deduction_leaves_exactly_one_ledger_row(
    engine, committed_stock
):
    """The ledger must not double-count or lose entries under contention."""
    seeded = committed_stock(quantity=8)

    outcomes = _deduct_in_parallel(engine, seeded, workers=8, quantity_each=1)
    assert outcomes.count("committed") == 8

    session = Session(engine)
    try:
        movements = (
            session.query(InventoryMovement)
            .join(Inventory, InventoryMovement.inventory_id == Inventory.id)
            .filter(Inventory.product_id == seeded["product_id"])
            .all()
        )
    finally:
        session.close()

    assert len(movements) == 8
    # Each thread saw a distinct running total, proving the reads were serialised.
    assert sorted(m.quantity_after for m in movements) == [0, 1, 2, 3, 4, 5, 6, 7]
