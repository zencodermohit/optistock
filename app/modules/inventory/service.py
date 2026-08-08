from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Tuple
from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.core.exceptions import OptiStockException


class InventoryService:
    """
    Transaction Boundary Rule:
    This service NEVER calls db.commit() or db.rollback().
    It only stages changes with flush(). The caller (router or
    orchestrating service) owns the transaction and decides when to commit.
    This prevents partial-commit bugs in multi-step operations like Sales.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_inventory(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        warehouse_id: UUID = None,
    ) -> Tuple[List[Inventory], int]:
        """Fetch paginated inventory levels. Optionally filter by warehouse."""
        query = (
            self.db.query(Inventory)
            .join(Product, Inventory.product_id == Product.id)
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            .filter(
                Product.company_id == company_id, Warehouse.company_id == company_id
            )
        )

        if warehouse_id:
            query = query.filter(Inventory.warehouse_id == warehouse_id)

        total = query.count()
        inventory_items = query.offset(skip).limit(limit).all()

        return inventory_items, total

    def get_or_create_inventory(
        self, product_id: UUID, warehouse_id: UUID
    ) -> Inventory:
        inv = (
            self.db.query(Inventory)
            .filter(
                Inventory.product_id == product_id,
                Inventory.warehouse_id == warehouse_id,
            )
            .first()
        )

        if not inv:
            inv = Inventory(
                product_id=product_id, warehouse_id=warehouse_id, quantity=0
            )
            self.db.add(inv)
            self.db.flush()  # Stage only — do NOT commit
        return inv

    def adjust_inventory(
        self,
        product_id: UUID,
        warehouse_id: UUID,
        company_id: UUID,
        quantity_change: int,
        movement_type: str,
        reference_id: str = None,
    ) -> Inventory:
        # Step 1: Ensure both references belong to the active tenant.
        product = (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.company_id == company_id)
            .first()
        )
        warehouse = (
            self.db.query(Warehouse)
            .filter(Warehouse.id == warehouse_id, Warehouse.company_id == company_id)
            .first()
        )
        if not product or not warehouse:
            raise OptiStockException(
                code="INVALID_TENANT_REFERENCE",
                message="Product and warehouse must belong to the active company.",
            )

        # Step 2: Ensure record exists
        self.get_or_create_inventory(product_id, warehouse_id)

        # Step 2: Lock the row! (Crucial for concurrency)
        inv = (
            self.db.query(Inventory)
            .filter(
                Inventory.product_id == product_id,
                Inventory.warehouse_id == warehouse_id,
            )
            .with_for_update()
            .first()
        )

        # Step 3: Business Logic (Prevent negative stock)
        new_quantity = inv.quantity + quantity_change
        if new_quantity < 0:
            raise OptiStockException(
                code="INSUFFICIENT_STOCK",
                message=f"Cannot deduct {-quantity_change} units. Only {inv.quantity} available.",
            )

        # Step 4: Update stock
        inv.quantity = new_quantity

        # Step 5: Write the audit ledger
        movement = InventoryMovement(
            inventory_id=inv.id,
            movement_type=movement_type,
            quantity_change=quantity_change,
            quantity_after=new_quantity,
            reference_id=reference_id,
        )
        self.db.add(movement)

        # Step 6: Flush changes — caller will commit the full transaction
        self.db.flush()
        return inv
