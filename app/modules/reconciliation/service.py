from sqlalchemy.orm import Session, joinedload
from uuid import UUID
from typing import List, Tuple

from app.modules.reconciliation.models import Reconciliation, ReconciliationItem
from app.modules.products.models import Product
from app.modules.warehouses.models import Warehouse
from app.modules.reconciliation.schemas import ReconciliationCreate
from app.modules.inventory.service import InventoryService
from app.core.exceptions import OptiStockException, ResourceNotFoundError


class ReconciliationService:
    def __init__(self, db: Session):
        self.db = db
        self.inventory_service = InventoryService(db)

    def get_reconciliations(
        self, company_id: UUID, skip: int = 0, limit: int = 50, status: str = None
    ) -> Tuple[List[Reconciliation], int]:
        """Fetch paginated reconciliations with eager-loaded items."""
        query = (
            self.db.query(Reconciliation)
            .options(joinedload(Reconciliation.items))
            .filter(Reconciliation.company_id == company_id)
        )
        if status:
            query = query.filter(Reconciliation.status == status)

        total = query.count()
        recons = query.offset(skip).limit(limit).all()
        return recons, total

    def get_reconciliation_by_id(
        self, recon_id: UUID, company_id: UUID
    ) -> Reconciliation:
        recon = (
            self.db.query(Reconciliation)
            .options(joinedload(Reconciliation.items))
            .filter(
                Reconciliation.id == recon_id, Reconciliation.company_id == company_id
            )
            .first()
        )
        if not recon:
            raise ResourceNotFoundError("Reconciliation", str(recon_id))
        return recon

    def create_reconciliation(
        self, recon_in: ReconciliationCreate, company_id: UUID
    ) -> Reconciliation:
        """Submits a cycle count batch. Defaults to 'pending'."""
        try:
            warehouse = (
                self.db.query(Warehouse)
                .filter(
                    Warehouse.id == recon_in.warehouse_id,
                    Warehouse.company_id == company_id,
                )
                .first()
            )
            product_count = (
                self.db.query(Product)
                .filter(
                    Product.id.in_([item.product_id for item in recon_in.items]),
                    Product.company_id == company_id,
                )
                .count()
            )
            if not warehouse or product_count != len(
                {item.product_id for item in recon_in.items}
            ):
                raise OptiStockException(
                    code="INVALID_TENANT_REFERENCE",
                    message="Warehouse and products must belong to the active company.",
                )

            recon = Reconciliation(
                company_id=company_id,
                warehouse_id=recon_in.warehouse_id,
                status="pending",
            )
            self.db.add(recon)
            self.db.flush()

            for item in recon_in.items:
                recon_item = ReconciliationItem(
                    reconciliation_id=recon.id,
                    product_id=item.product_id,
                    expected_quantity=item.expected_quantity,
                    actual_quantity=item.actual_quantity,
                    discrepancy_reason=item.discrepancy_reason,
                )
                self.db.add(recon_item)

            self.db.flush()
            return recon
        except Exception as e:
            raise e

    def approve_reconciliation(
        self, reconciliation_id: UUID, company_id: UUID
    ) -> Reconciliation:
        """[ALREADY EXISTED] Approves batch and physically modifies inventory ledger."""
        recon = (
            self.db.query(Reconciliation)
            .filter(
                Reconciliation.id == reconciliation_id,
                Reconciliation.company_id == company_id,
            )
            .first()
        )
        if not recon:
            raise ResourceNotFoundError("Reconciliation", str(reconciliation_id))

        if recon.status != "pending":
            raise OptiStockException(
                code="INVALID_STATUS",
                message="Only pending reconciliations can be approved.",
            )

        items = (
            self.db.query(ReconciliationItem)
            .filter(ReconciliationItem.reconciliation_id == reconciliation_id)
            .all()
        )

        for item in items:
            discrepancy = item.actual_quantity - item.expected_quantity

            # Only hit the database if there was actually a difference!
            if discrepancy != 0:
                self.inventory_service.adjust_inventory(
                    product_id=item.product_id,
                    warehouse_id=recon.warehouse_id,
                    company_id=company_id,
                    quantity_change=discrepancy,
                    movement_type="reconciliation_adjustment",
                    reference_id=str(recon.id),
                )

        recon.status = "approved"
        self.db.flush()

        return recon

    def reject_reconciliation(
        self, reconciliation_id: UUID, company_id: UUID
    ) -> Reconciliation:
        """Rejects the batch. Does NOT modify inventory."""
        recon = (
            self.db.query(Reconciliation)
            .filter(
                Reconciliation.id == reconciliation_id,
                Reconciliation.company_id == company_id,
            )
            .first()
        )
        if not recon:
            raise ResourceNotFoundError("Reconciliation", str(reconciliation_id))

        if recon.status != "pending":
            raise OptiStockException(
                code="INVALID_STATUS",
                message="Only pending reconciliations can be rejected.",
            )

        recon.status = "rejected"
        self.db.flush()

        return recon
