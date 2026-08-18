from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from typing import List, Tuple
from app.modules.sales.models import Customer, Sale, SaleItem
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.modules.sales.schemas import SaleCreate
from app.modules.inventory.service import InventoryService
from app.modules.events import types as event_types
from app.modules.events.publisher import record_event
from app.core.exceptions import OptiStockException, ResourceNotFoundError


class SaleService:
    def __init__(self, db: Session):
        self.db = db
        self.inventory_service = InventoryService(db)

    def get_sales(
        self, company_id: UUID, skip: int = 0, limit: int = 50, status: str = None
    ) -> Tuple[List[Sale], int]:
        """Returns paginated sales and the total count.

        No joinedload here: the list representation does not include line items,
        so eager-loading them would fetch hundreds of rows only to discard them.
        """
        query = self.db.query(Sale).filter(Sale.company_id == company_id)

        if status:
            query = query.filter(Sale.status == status)

        total = query.count()
        sales = query.order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()

        return sales, total

    def ledger(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 100,
        status: str = None,
    ) -> Tuple[List[dict], int, dict]:
        """Sales with names joined in, plus the totals for the window shown.

        The read model for the Sales screen, in the same sense as the purchase
        order pipeline: SaleResponse returns customer_id and warehouse_id, and
        a page rendering UUIDs at a person is not a page.

        Line items stay out, deliberately -- SaleResponse leaves them out
        because a page of fifty sales would drag several hundred item rows
        across the wire that the list never shows, and that reasoning does not
        stop being true here. What IS included is each sale's unit count, which
        is the one thing about the items a ledger row needs: it is the demand
        signal every forecast on this system is built from.
        """
        base = self.db.query(Sale).filter(Sale.company_id == company_id)
        if status:
            base = base.filter(Sale.status == status)

        total = base.count()
        sales = base.order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
        if not sales:
            return [], total, {"revenue": 0.0, "units": 0, "orders": 0}

        sale_ids = [s.id for s in sales]

        customers = dict(
            self.db.query(Customer.id, Customer.name)
            .filter(Customer.company_id == company_id)
            .all()
        )
        warehouses = dict(
            self.db.query(Warehouse.id, Warehouse.name)
            .filter(Warehouse.company_id == company_id)
            .all()
        )
        # One grouped query for every unit count on the page, rather than one
        # per row. The N+1 here would be invisible at ten sales and painful at
        # a hundred.
        units = dict(
            self.db.query(
                SaleItem.sale_id,
                func.coalesce(func.sum(SaleItem.quantity), 0),
            )
            .filter(SaleItem.sale_id.in_(sale_ids))
            .group_by(SaleItem.sale_id)
            .all()
        )
        lines = dict(
            self.db.query(SaleItem.sale_id, func.count(SaleItem.id))
            .filter(SaleItem.sale_id.in_(sale_ids))
            .group_by(SaleItem.sale_id)
            .all()
        )

        rows = [
            {
                "id": str(sale.id),
                "status": sale.status,
                "created_at": sale.created_at,
                "total_amount": float(sale.total_amount or 0),
                "customer_name": customers.get(sale.customer_id, "Unknown customer"),
                "customer_id": str(sale.customer_id),
                "warehouse_name": warehouses.get(
                    sale.source_warehouse_id, "Unknown warehouse"
                ),
                "units": int(units.get(sale.id, 0)),
                "lines": int(lines.get(sale.id, 0)),
            }
            for sale in sales
        ]

        # Totals for what is on screen, not for all time. A footer claiming a
        # figure the reader cannot see the rows behind is a footer they cannot
        # check.
        summary = {
            "revenue": round(sum(r["total_amount"] for r in rows), 2),
            "units": sum(r["units"] for r in rows),
            "orders": len(rows),
        }
        return rows, total, summary

    def get_sale_by_id(self, sale_id: UUID, company_id: UUID) -> Sale:
        """A single sale with its line items.

        joinedload IS worth it here — the detail view renders every item, and
        without it this would be one query per line (the N+1 problem).
        """
        sale = (
            self.db.query(Sale)
            .options(joinedload(Sale.items))
            .filter(Sale.id == sale_id, Sale.company_id == company_id)
            .first()
        )
        if not sale:
            raise ResourceNotFoundError(resource="Sale", resource_id=str(sale_id))
        return sale

    def create_sale(self, sale_in: SaleCreate, company_id: UUID) -> Sale:
        """
        Creates a sale and deducts inventory in a single atomic transaction.
        If inventory is insufficient, the entire sale is rolled back.
        """
        try:
            customer = (
                self.db.query(Customer)
                .filter(
                    Customer.id == sale_in.customer_id,
                    Customer.company_id == company_id,
                )
                .first()
            )
            warehouse = (
                self.db.query(Warehouse)
                .filter(
                    Warehouse.id == sale_in.source_warehouse_id,
                    Warehouse.company_id == company_id,
                )
                .first()
            )
            product_count = (
                self.db.query(Product)
                .filter(
                    Product.id.in_([item.product_id for item in sale_in.items]),
                    Product.company_id == company_id,
                )
                .count()
            )
            if (
                not customer
                or not warehouse
                or product_count != len({item.product_id for item in sale_in.items})
            ):
                raise OptiStockException(
                    code="INVALID_TENANT_REFERENCE",
                    message="Customer, warehouse, and products must belong to the active company.",
                )

            # 1. Calculate the total amount using a generator expression
            total_amount = sum(
                item.quantity * item.unit_price for item in sale_in.items
            )

            # 2. Create the Sale Header
            sale = Sale(
                company_id=company_id,
                customer_id=sale_in.customer_id,
                source_warehouse_id=sale_in.source_warehouse_id,
                status="completed",
                total_amount=total_amount,
            )
            self.db.add(sale)

            # flush() gives us the sale.id without permanently saving yet
            self.db.flush()

            # 3. Process Items and Deduct Inventory
            for item in sale_in.items:
                sale_item = SaleItem(
                    sale_id=sale.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                )
                self.db.add(sale_item)

                # CRITICAL: Call InventoryService to deduct stock.
                # If this raises InsufficientStockError, it jumps to the except block.
                self.inventory_service.adjust_inventory(
                    product_id=item.product_id,
                    warehouse_id=sale_in.source_warehouse_id,
                    company_id=company_id,
                    quantity_change=-item.quantity,  # Negative because it's a sale deduction
                    movement_type="sale",
                    reference_id=str(sale.id),
                )

            # 4. If we reach here, we successfully deducted stock for all items.
            #
            # One event for the sale, on top of the per-line stock.moved events
            # the inventory service already staged. They answer different
            # questions: "what did this customer buy" is not reconstructable
            # from a handful of unrelated stock deductions.
            record_event(
                self.db,
                company_id=company_id,
                event_type=event_types.SALE_COMPLETED,
                aggregate_type=event_types.AGGREGATE_SALE,
                aggregate_id=sale.id,
                payload={
                    "customer_name": customer.name,
                    "warehouse_name": warehouse.name,
                    "line_count": len(sale_in.items),
                    "unit_count": sum(item.quantity for item in sale_in.items),
                    "total_amount": float(total_amount),
                },
            )

            self.db.flush()
            return sale

        except Exception as e:
            # 5. If ANYTHING goes wrong (e.g., negative stock constraint hit), roll back EVERYTHING.
            raise e
