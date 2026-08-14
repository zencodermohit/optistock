from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.core.database import get_db
from app.core.exceptions import OptiStockException, ResourceNotFoundError
from app.core.dependencies import RequireRole, get_current_user
from app.modules.warehouses.schemas import (
    WarehouseCreate,
    WarehouseResponse,
    WarehouseUpdate,
    PaginatedWarehousesResponse,
)
from app.modules.warehouses.service import WarehouseService

from app.modules.analytics.readmodels import warehouse_site
from app.modules.warehouses.command import command_center, network

router = APIRouter(prefix="/api/v1/warehouses", tags=["Warehouses"])


def get_warehouse_service(db: Session = Depends(get_db)) -> WarehouseService:
    return WarehouseService(db)


@router.post("/", response_model=WarehouseResponse, status_code=201)
def create_warehouse(
    wh_in: WarehouseCreate,
    service: WarehouseService = Depends(get_warehouse_service),
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    try:
        wh = service.create_warehouse(wh_in, UUID(current_user["company_id"]))
        db.commit()
        return wh
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.get("/network")
def get_network(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Layer 1: every site as a node, with the stock moving between them."""
    return network(db, UUID(current_user["company_id"]))


@router.get("/{wh_id}/command-center")
def get_command_center(
    wh_id: UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Layer 2: one warehouse, broken into zones, with its live feed."""
    data = command_center(db, UUID(current_user["company_id"]), wh_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return data


@router.get("/site")
def get_site(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Every warehouse as a place, for the 3D landing screen.

    Capacity sizes the building, utilisation lights it, and out-of-stock lines
    put a marker above it. The scene is drawn from these numbers rather than
    beside them.

    Declared ABOVE /{wh_id}. FastAPI matches in declaration order, and below it
    "site" is read as a warehouse id and rejected as a malformed UUID -- which
    is exactly how this was found.
    """
    return {"data": warehouse_site(db, UUID(current_user["company_id"]))}


@router.get("/{wh_id}", response_model=WarehouseResponse)
def get_warehouse(
    wh_id: UUID,
    service: WarehouseService = Depends(get_warehouse_service),
    current_user: dict = Depends(get_current_user),
):
    try:
        return service.get_warehouse(wh_id, UUID(current_user["company_id"]))
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.get("/", response_model=PaginatedWarehousesResponse)
def get_warehouses(
    skip: int = 0,
    limit: int = 50,
    is_active: bool = None,
    service: WarehouseService = Depends(get_warehouse_service),
    current_user: dict = Depends(get_current_user),
):
    company_id = UUID(current_user["company_id"])
    warehouses, total = service.get_warehouses(
        company_id=company_id, skip=skip, limit=limit, is_active=is_active
    )
    return {"total": total, "skip": skip, "limit": limit, "data": warehouses}


@router.patch("/{wh_id}", response_model=WarehouseResponse)
def update_warehouse(
    wh_id: UUID,
    wh_in: WarehouseUpdate,
    service: WarehouseService = Depends(get_warehouse_service),
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    try:
        wh = service.update_warehouse(wh_id, wh_in, UUID(current_user["company_id"]))
        db.commit()
        return wh
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.delete("/{wh_id}", response_model=WarehouseResponse)
def delete_warehouse(
    wh_id: UUID,
    service: WarehouseService = Depends(get_warehouse_service),
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    try:
        wh = service.delete_warehouse(wh_id, UUID(current_user["company_id"]))
        db.commit()
        return wh
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
