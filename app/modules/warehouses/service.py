from uuid import UUID
from sqlalchemy.orm import Session
from app.modules.warehouses.repository import WarehouseRepository
from app.modules.warehouses.schemas import WarehouseCreate, WarehouseUpdate
from app.modules.warehouses.models import Warehouse
from app.core.exceptions import OptiStockException, ResourceNotFoundError


class WarehouseService:
    def __init__(self, db: Session):
        self.repo = WarehouseRepository(db)

    def create_warehouse(self, wh_in: WarehouseCreate, company_id: UUID) -> Warehouse:
        if self.repo.get_by_location(wh_in.location_code, company_id):
            raise OptiStockException(
                "DUPLICATE_LOCATION", "Warehouse location code already exists."
            )
        return self.repo.create(wh_in, company_id)

    def get_warehouse(self, wh_id: UUID, company_id: UUID) -> Warehouse:
        wh = self.repo.get_by_id(wh_id, company_id)
        if not wh:
            raise ResourceNotFoundError("Warehouse", str(wh_id))
        return wh

    def get_warehouses(
        self, company_id: UUID, skip: int = 0, limit: int = 50, is_active: bool = None
    ):
        return self.repo.get_all(
            company_id=company_id, skip=skip, limit=limit, is_active=is_active
        )

    def update_warehouse(
        self, wh_id: UUID, wh_in: WarehouseUpdate, company_id: UUID
    ) -> Warehouse:
        wh = self.get_warehouse(wh_id, company_id)
        return self.repo.update(wh, wh_in)

    def delete_warehouse(self, wh_id: UUID, company_id: UUID) -> Warehouse:
        wh = self.get_warehouse(wh_id, company_id)
        update_schema = WarehouseUpdate(is_active=False)
        return self.repo.update(wh, update_schema)
