from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from app.modules.warehouses.models import Warehouse
from app.modules.warehouses.schemas import WarehouseCreate, WarehouseUpdate


class WarehouseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, warehouse_id: UUID, company_id: UUID) -> Optional[Warehouse]:
        return (
            self.db.query(Warehouse)
            .filter(Warehouse.id == warehouse_id, Warehouse.company_id == company_id)
            .first()
        )

    def get_by_location(
        self, location_code: str, company_id: UUID
    ) -> Optional[Warehouse]:
        return (
            self.db.query(Warehouse)
            .filter(
                Warehouse.location_code == location_code,
                Warehouse.company_id == company_id,
            )
            .first()
        )

    def get_all(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        is_active: Optional[bool] = None,
    ):
        query = self.db.query(Warehouse).filter(Warehouse.company_id == company_id)
        if is_active is not None:
            query = query.filter(Warehouse.is_active == is_active)
        total = query.count()
        warehouses = query.offset(skip).limit(limit).all()
        return warehouses, total

    def create(self, wh_in: WarehouseCreate, company_id: UUID) -> Warehouse:
        db_wh = Warehouse(**wh_in.model_dump(), company_id=company_id)
        self.db.add(db_wh)
        self.db.flush()
        return db_wh

    def update(self, db_wh: Warehouse, wh_in: WarehouseUpdate) -> Warehouse:
        update_data = wh_in.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(db_wh, field, value)
        self.db.flush()
        return db_wh
