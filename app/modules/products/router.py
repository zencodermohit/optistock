from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
from app.core.dependencies import get_current_user, RequireRole
from app.core.rate_limit import limiter
import csv
import io

from app.core.database import get_db
from app.core.exceptions import OptiStockException, ResourceNotFoundError
from app.modules.products.schemas import (
    ProductCreate,
    ProductUpdate,
    ProductResponse,
    PaginatedProductsResponse,
)
from app.modules.products.service import ProductService

from app.modules.products.intelligence import product_intelligence
from app.modules.products.command_center import product_command_center

router = APIRouter(prefix="/api/v1/products", tags=["Products"])

# ROUTE ORDER MATTERS. FastAPI matches in declaration order and stops at the
# first hit, so every literal path (/import-csv, /export-csv) must be declared
# BEFORE /{product_id}. Otherwise the UUID path parameter swallows them and the
# request fails validation with a 422 instead of reaching the intended handler.


# Dependency Injection: This automatically provides our Service to every route
def get_product_service(db: Session = Depends(get_db)) -> ProductService:
    return ProductService(db)


@router.get("/", response_model=PaginatedProductsResponse)
def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None, description="Match on SKU or product name"),
    abc_class: Optional[str] = Query(
        None,
        pattern="^[ABCabc]$",
        description="Revenue class from the nightly Pareto analysis",
    ),
    status: Optional[str] = Query(None, description="active | archived | discontinued"),
    service: ProductService = Depends(get_product_service),
    current_user: dict = Depends(get_current_user),
):
    """List products. Filtering is applied before pagination, so `total`
    reflects the filtered set rather than the page."""
    products, total = service.list_products(
        company_id=current_user["company_id"],
        skip=skip,
        limit=limit,
        search=search,
        abc_class=abc_class,
        status=status,
    )
    return {"total": total, "skip": skip, "limit": limit, "data": products}


@router.post("/", response_model=ProductResponse, status_code=201)
def create_product(
    product_in: ProductCreate,
    service: ProductService = Depends(get_product_service),
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    try:
        product = service.create_product(product_in, UUID(current_user["company_id"]))
        db.commit()
        return product
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


# --- literal paths: must stay above /{product_id} ---------------------------


@router.post("/import-csv")
@limiter.limit("5/minute")
def import_products_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    """
    Bulk import products from a CSV file. Rate limited to prevent abuse.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Invalid file format. Must be CSV.")

    content = file.file.read().decode("utf-8")
    reader = csv.DictReader(io.StringIO(content))
    service = ProductService(db)

    imported_count = 0
    try:
        for row in reader:
            try:
                # Assume CSV has headers matching ProductCreate schema
                product_data = ProductCreate(**row)
                service.create_product(product_data, UUID(current_user["company_id"]))
                imported_count += 1
            except Exception as e:
                # In a real app we might collect errors and return them, but we'll fail fast here
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed on row {imported_count + 1}: {str(e)}",
                )
        db.commit()
    except Exception as e:
        db.rollback()
        raise e

    return {"message": f"Successfully imported {imported_count} products."}


@router.get("/export-csv")
@limiter.limit("10/minute")
def export_products_csv(
    request: Request,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Export all products as a streaming CSV to avoid blowing up memory.
    """
    service = ProductService(db)
    products, _ = service.list_products(
        company_id=current_user["company_id"], skip=0, limit=10000
    )  # In real app, might yield directly from DB cursor

    output = io.StringIO()
    writer = csv.writer(output)

    # Write Headers
    writer.writerow(
        ["id", "sku", "name", "category", "unit_cost", "selling_price", "status"]
    )

    for p in products:
        writer.writerow(
            [p.id, p.sku, p.name, p.category, p.unit_cost, p.selling_price, p.status]
        )

    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_export.csv"},
    )


# --- parameterised paths: must stay below every literal path ----------------


@router.get("/intelligence")
def get_intelligence(
    days: int = Query(30, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Every SKU classified by how it is behaving, for the Products hub.

    Above /{product_id}: FastAPI matches in declaration order, and below it
    "intelligence" is read as a product id and rejected as a malformed UUID.
    """
    return product_intelligence(
        db, UUID(current_user["company_id"]), days=days
    )


@router.get("/{product_id}/command-center")
def get_command_center(
    product_id: UUID,
    days: int = Query(90, ge=7, le=365),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Everything known about one SKU: demand, stock, supply and what to do.

    Above the bare /{product_id} for the same reason "intelligence" is: FastAPI
    matches in declaration order, and a suffixed path declared later never wins
    against a bare parameter declared earlier.
    """
    data = product_command_center(
        db, UUID(current_user["company_id"]), product_id, days=days
    )
    if data is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return data


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: UUID,
    service: ProductService = Depends(get_product_service),
    current_user: dict = Depends(get_current_user),
):
    try:
        return service.get_product(product_id, UUID(current_user["company_id"]))
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: UUID,
    product_in: ProductUpdate,
    service: ProductService = Depends(get_product_service),
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
):
    try:
        product = service.update_product(
            product_id, product_in, UUID(current_user["company_id"])
        )
        db.commit()
        return product
    # ResourceNotFoundError subclasses OptiStockException, so it must be caught
    # first or a missing product is reported as 400 here but 404 on GET/DELETE.
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e


@router.delete("/{product_id}", response_model=ProductResponse)
def archive_product(
    product_id: UUID,
    service: ProductService = Depends(get_product_service),
    current_user: dict = Depends(RequireRole(["admin", "supply_chain"])),
    db: Session = Depends(get_db),
):
    try:
        product = service.delete_product(product_id, UUID(current_user["company_id"]))
        db.commit()
        return product
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
