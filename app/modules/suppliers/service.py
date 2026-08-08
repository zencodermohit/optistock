from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from typing import List, Tuple

from app.modules.suppliers.models import Supplier
from app.modules.suppliers.schemas import SupplierCreate, SupplierUpdate
from app.core.exceptions import OptiStockException, ResourceNotFoundError


class SupplierService:
    def __init__(self, db: Session):
        self.db = db

    def get_suppliers(
        self, company_id: UUID, skip: int = 0, limit: int = 50, is_active: bool = None
    ) -> Tuple[List[Supplier], int]:
        """Returns paginated suppliers. Optionally filters by active status."""
        query = self.db.query(Supplier).filter(Supplier.company_id == company_id)

        if is_active is not None:
            query = query.filter(Supplier.is_active == is_active)

        total = query.count()
        suppliers = query.offset(skip).limit(limit).all()
        return suppliers, total

    def get_supplier_by_id(self, supplier_id: UUID, company_id: UUID) -> Supplier:
        """Fetches a tenant-owned supplier or raises a 404."""
        supplier = (
            self.db.query(Supplier)
            .filter(Supplier.id == supplier_id, Supplier.company_id == company_id)
            .first()
        )
        if not supplier:
            raise ResourceNotFoundError(
                resource="Supplier", resource_id=str(supplier_id)
            )
        return supplier

    def create_supplier(
        self, supplier_in: SupplierCreate, company_id: UUID
    ) -> Supplier:
        """Creates a new supplier."""
        supplier = Supplier(
            company_id=company_id,
            name=supplier_in.name,
            contact_email=supplier_in.contact_email,
            is_active=True,
        )
        self.db.add(supplier)
        try:
            self.db.flush()
            return supplier
        except IntegrityError:
            raise OptiStockException(
                code="CONFLICT",
                message="A database conflict occurred (e.g., duplicate unique field).",
            )

    def update_supplier(
        self, supplier_id: UUID, supplier_in: SupplierUpdate, company_id: UUID
    ) -> Supplier:
        """Updates only the fields provided by the user."""
        supplier = self.get_supplier_by_id(supplier_id, company_id)

        # Extract only the fields the user explicitly sent in the JSON body
        update_data = supplier_in.model_dump(exclude_unset=True)

        for key, value in update_data.items():
            setattr(supplier, key, value)

        self.db.flush()
        return supplier

    def delete_supplier(self, supplier_id: UUID, company_id: UUID) -> Supplier:
        """
        SOFT DELETE: We do not remove the row from the database!
        We just flip the is_active flag to False.
        """
        supplier = self.get_supplier_by_id(supplier_id, company_id)
        supplier.is_active = False

        self.db.flush()
        return supplier
