from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import func
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Dict, List, Tuple
from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.modules.events import types as event_types
from app.modules.events.publisher import record_event
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

        # Order follows intent. Browsing the catalogue, SKU is the order the
        # user can predict and scan. Asking for what is below its reorder point
        # is a triage question, and triage wants the worst first.
        order = Inventory.quantity.asc() if low_only else Product.sku.asc()
        rows = query.order_by(order).offset(skip).limit(limit).all()

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

    def get_traces(self, company_id: UUID, days: int = 30) -> Dict[UUID, List[int]]:
        """Daily closing quantity per stock line for the last `days` days.

        Reconstructed backwards from the current quantity rather than forwards
        from history. Walking forwards would need the closing balance from
        before the window as a starting point -- a second query per line, or a
        second pass over the whole ledger. Walking backwards, today's quantity
        is already known and each earlier day is the next day minus that day's
        movements. One grouped query, exact, and days with no movement fall out
        for free as a repeat of the day after.
        """
        start = datetime.now(timezone.utc).date() - timedelta(days=days - 1)

        current = {
            row.id: row.quantity
            for row in self.db.query(Inventory.id, Inventory.quantity)
            .join(Product, Inventory.product_id == Product.id)
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            .filter(
                Product.company_id == company_id, Warehouse.company_id == company_id
            )
            .all()
        }
        if not current:
            return {}

        # Net movement per line per day. Joined to the tenant rather than
        # filtered by a list of ids, so the query stays one statement whether
        # the tenant has three hundred lines or three hundred thousand.
        day = func.date(InventoryMovement.created_at).label("day")
        rows = (
            self.db.query(
                InventoryMovement.inventory_id,
                day,
                func.sum(InventoryMovement.quantity_change).label("delta"),
            )
            .join(Inventory, InventoryMovement.inventory_id == Inventory.id)
            .join(Product, Inventory.product_id == Product.id)
            .join(Warehouse, Inventory.warehouse_id == Warehouse.id)
            .filter(
                Product.company_id == company_id,
                Warehouse.company_id == company_id,
                InventoryMovement.created_at >= start,
            )
            .group_by(InventoryMovement.inventory_id, day)
            .all()
        )

        deltas: Dict[UUID, Dict[date, int]] = defaultdict(dict)
        for inventory_id, moved_on, delta in rows:
            deltas[inventory_id][moved_on] = int(delta)

        traces: Dict[UUID, List[int]] = {}
        for inventory_id, quantity in current.items():
            per_day = deltas.get(inventory_id, {})
            series = [0] * days
            running = quantity
            for offset in range(days - 1, -1, -1):
                series[offset] = running
                running -= per_day.get(start + timedelta(days=offset), 0)
            traces[inventory_id] = series

        return traces

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
        previous_quantity = inv.quantity
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

        # Step 6: Announce it.
        #
        # In the same transaction as the change, so the event cannot describe a
        # movement that gets rolled back. The payload is deliberately fat --
        # SKU and name as well as ids -- because a consumer that has to query
        # the database to understand a message is coupled to the producer's
        # schema, and the point of the event is to break that coupling.
        record_event(
            self.db,
            company_id=company_id,
            event_type=event_types.STOCK_MOVED,
            aggregate_type=event_types.AGGREGATE_INVENTORY,
            aggregate_id=inv.id,
            payload={
                "sku": product.sku,
                "product_name": product.name,
                "warehouse_name": warehouse.name,
                "movement_type": movement_type,
                "quantity_change": quantity_change,
                "quantity_after": new_quantity,
                "reorder_point": inv.reorder_point or 0,
                "reference": reference_id,
            },
        )

        # A crossing, not a state. `stock.moved` says the number changed;
        # these say it changed *through* a threshold, which is the thing
        # anyone downstream actually wants to react to. Emitting them only on
        # the crossing means a line that sits low for a week produces one
        # event, not one per sale.
        crossed_reorder = (
            inv.reorder_point
            and inv.reorder_point > 0
            and new_quantity <= inv.reorder_point
            and previous_quantity > inv.reorder_point
        )
        if new_quantity == 0 and previous_quantity > 0:
            self._announce_threshold(
                event_types.STOCK_DEPLETED, inv, product, warehouse, company_id
            )
        elif crossed_reorder:
            self._announce_threshold(
                event_types.STOCK_BELOW_REORDER_POINT,
                inv,
                product,
                warehouse,
                company_id,
            )

        # Step 7: Flush changes — caller will commit the full transaction
        self.db.flush()
        return inv

    def _announce_threshold(
        self, event_type: str, inv, product, warehouse, company_id: UUID
    ) -> None:
        record_event(
            self.db,
            company_id=company_id,
            event_type=event_type,
            aggregate_type=event_types.AGGREGATE_INVENTORY,
            aggregate_id=inv.id,
            payload={
                "sku": product.sku,
                "product_name": product.name,
                "warehouse_name": warehouse.name,
                "quantity": inv.quantity,
                "reorder_point": inv.reorder_point or 0,
            },
        )
