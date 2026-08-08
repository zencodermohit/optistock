from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Tuple
from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.core.exceptions import OptiStockException, ResourceNotFoundError


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
        search: str = None,
        low_only: bool = False,
    ) -> Tuple[List[dict], int]:
        """Paginated stock levels, joined with the names needed to display them.

        Returns dicts rather than Inventory rows because the response carries
        product and warehouse names. Denormalising them here means a client
        never has to fetch the whole catalogue just to label a table.
        """
        query = self._enriched_query(company_id)

        if warehouse_id:
            query = query.filter(Inventory.warehouse_id == warehouse_id)
        if search:
            pattern = f"%{search}%"
            query = query.filter(
                Product.sku.ilike(pattern) | Product.name.ilike(pattern)
            )
        if low_only:
            # reorder_point 0 means "not configured", so it never counts as low.
            query = query.filter(
                Inventory.reorder_point > 0,
                Inventory.quantity <= Inventory.reorder_point,
            )

        total = query.count()
        rows = query.order_by(Inventory.quantity.asc()).offset(skip).limit(limit).all()

        return [self._to_line(row) for row in rows], total

    def get_inventory_line(self, inventory_id: UUID, company_id: UUID) -> dict:
        """One stock line, in the same enriched shape the list endpoint returns.

        Consistent on purpose: a client that adjusts stock gets back a row
        identical in shape to the one already in its table, so it can swap it in
        place with no second request and no special case.
        """
        row = (
            self._enriched_query(company_id)
            .filter(Inventory.id == inventory_id)
            .first()
        )
        if row is None:
            raise ResourceNotFoundError(
                resource="Inventory", resource_id=str(inventory_id)
            )
        return self._to_line(row)

    def _enriched_query(self, company_id: UUID):
        """Stock joined with the product and warehouse names needed to show it.

        Shared by the list and single-row reads so the two can never drift into
        returning different shapes for the same thing.
        """
        return (
            self.db.query(
                Inventory.id,
                Inventory.product_id,
                Inventory.warehouse_id,
                Inventory.quantity,
                Inventory.last_counted_at,
                Inventory.reorder_point,
                Product.sku,
                Product.name.label("product_name"),
                Product.category,
                Product.abc_class,
                Warehouse.name.label("warehouse_name"),
            )
            .join(Product, Inventory.product_id == Product.id)
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            # Both sides checked: verifying only the product would let a caller
            # pair their own product with another tenant's warehouse.
            .filter(
                Product.company_id == company_id, Warehouse.company_id == company_id
            )
        )

    @staticmethod
    def _to_line(row) -> dict:
        return {
            **row._mapping,
            "is_low": row.reorder_point > 0 and row.quantity <= row.reorder_point,
        }

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
