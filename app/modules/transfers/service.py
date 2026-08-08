from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from datetime import datetime, UTC
from typing import List, Tuple

from app.modules.transfers.models import Transfer, TransferItem
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.modules.transfers.schemas import TransferCreate
from app.modules.inventory.service import InventoryService
from app.core.exceptions import OptiStockException, ResourceNotFoundError


class TransferService:
    def __init__(self, db: Session):
        self.db = db
        self.inventory_service = InventoryService(db)

    def get_transfers(
        self, company_id: UUID, skip: int = 0, limit: int = 50, status: str = None
    ) -> Tuple[List[Transfer], int]:
        """Fetch paginated transfers with eager-loaded items."""
        query = (
            self.db.query(Transfer)
            .options(joinedload(Transfer.items))
            .filter(Transfer.company_id == company_id)
        )
        if status:
            query = query.filter(Transfer.status == status)

        total = query.count()
        transfers = query.offset(skip).limit(limit).all()
        return transfers, total

    def get_transfer_by_id(self, transfer_id: UUID, company_id: UUID) -> Transfer:
        """Fetch a single transfer with eager-loaded items."""
        transfer = (
            self.db.query(Transfer)
            .options(joinedload(Transfer.items))
            .filter(Transfer.id == transfer_id, Transfer.company_id == company_id)
            .first()
        )
        if not transfer:
            raise ResourceNotFoundError("Transfer", str(transfer_id))
        return transfer

    def create_transfer(
        self, transfer_in: TransferCreate, company_id: UUID
    ) -> Transfer:
        """Create a new transfer in the 'pending' state."""
        # Business Rule: Cannot transfer to the same warehouse
        if transfer_in.source_warehouse_id == transfer_in.destination_warehouse_id:
            raise OptiStockException(
                code="INVALID_TRANSFER",
                message="Source and destination warehouses must be different.",
            )

        try:
            warehouses = (
                self.db.query(Warehouse)
                .filter(
                    Warehouse.id.in_(
                        [
                            transfer_in.source_warehouse_id,
                            transfer_in.destination_warehouse_id,
                        ]
                    ),
                    Warehouse.company_id == company_id,
                )
                .count()
            )
            product_count = (
                self.db.query(Product)
                .filter(
                    Product.id.in_([item.product_id for item in transfer_in.items]),
                    Product.company_id == company_id,
                )
                .count()
            )
            if warehouses != 2 or product_count != len(
                {item.product_id for item in transfer_in.items}
            ):
                raise OptiStockException(
                    code="INVALID_TENANT_REFERENCE",
                    message="Warehouses and products must belong to the active company.",
                )

            transfer = Transfer(
                company_id=company_id,
                source_warehouse_id=transfer_in.source_warehouse_id,
                destination_warehouse_id=transfer_in.destination_warehouse_id,
                status="pending",
            )
            self.db.add(transfer)
            self.db.flush()

            for item in transfer_in.items:
                transfer_item = TransferItem(
                    transfer_id=transfer.id,
                    product_id=item.product_id,
                    quantity=item.quantity,
                )
                self.db.add(transfer_item)

            self.db.flush()
            return transfer
        except Exception as e:
            raise e

    def mark_as_shipped(self, transfer_id: UUID, company_id: UUID) -> Transfer:
        """[ALREADY EXISTED] Deducts stock from source warehouse."""
        transfer = (
            self.db.query(Transfer)
            .filter(Transfer.id == transfer_id, Transfer.company_id == company_id)
            .first()
        )
        if not transfer:
            raise ResourceNotFoundError("Transfer", str(transfer_id))

        if transfer.status != "pending":
            raise OptiStockException(
                code="INVALID_STATUS", message="Only pending transfers can be shipped."
            )

        items = (
            self.db.query(TransferItem)
            .filter(TransferItem.transfer_id == transfer_id)
            .all()
        )

        for item in items:
            self.inventory_service.adjust_inventory(
                product_id=item.product_id,
                warehouse_id=transfer.source_warehouse_id,
                company_id=company_id,
                quantity_change=-item.quantity,  # NEGATIVE: stock leaves
                movement_type="transfer_out",
                reference_id=str(transfer.id),
            )

        transfer.status = "in_transit"
        transfer.shipped_at = datetime.now(UTC)
        self.db.flush()

        return transfer

    def mark_as_completed(self, transfer_id: UUID, company_id: UUID) -> Transfer:
        """[ALREADY EXISTED] Adds stock to destination warehouse."""
        transfer = (
            self.db.query(Transfer)
            .filter(Transfer.id == transfer_id, Transfer.company_id == company_id)
            .first()
        )
        if not transfer:
            raise ResourceNotFoundError("Transfer", str(transfer_id))

        if transfer.status != "in_transit":
            raise OptiStockException(
                code="INVALID_STATUS",
                message="Only in-transit transfers can be completed.",
            )

        items = (
            self.db.query(TransferItem)
            .filter(TransferItem.transfer_id == transfer_id)
            .all()
        )

        for item in items:
            self.inventory_service.adjust_inventory(
                product_id=item.product_id,
                warehouse_id=transfer.destination_warehouse_id,
                company_id=company_id,
                quantity_change=item.quantity,  # POSITIVE: stock arrives
                movement_type="transfer_in",
                reference_id=str(transfer.id),
            )

        transfer.status = "completed"
        transfer.received_at = datetime.now(UTC)
        self.db.flush()

        return transfer
