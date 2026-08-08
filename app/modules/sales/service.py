from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from typing import List, Tuple
from app.modules.sales.models import Customer, Sale, SaleItem
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.modules.sales.schemas import SaleCreate
from app.modules.inventory.service import InventoryService
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
            self.db.flush()
            return sale

        except Exception as e:
            # 5. If ANYTHING goes wrong (e.g., negative stock constraint hit), roll back EVERYTHING.
            raise e
