from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional

from app.core.database import get_db
from app.core.dependencies import RequireRole
from app.core.exceptions import ResourceNotFoundError

from app.modules.companies.schemas import (
    CompanyCreate,
    CompanyUpdate,
    CompanyResponse,
    PaginatedCompaniesResponse,
)
from app.modules.companies.service import CompanyService

router = APIRouter(prefix="/api/v1/companies", tags=["Companies"])


@router.post("/", response_model=CompanyResponse, status_code=201)
def create_company(
    company_in: CompanyCreate,
    db: Session = Depends(get_db),
    # Only platform admins can onboard new companies
    _: dict = Depends(RequireRole(["platform_admin"])),
):
    """Create a new company (tenant onboarding)."""
    service = CompanyService(db)
    try:
        company = service.create_company(company_in)
        db.commit()
        return company
    except Exception as e:
        db.rollback()
        raise e


@router.get("/", response_model=PaginatedCompaniesResponse)
def get_companies(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _: dict = Depends(RequireRole(["platform_admin"])),
):
    """List all companies. Admin only."""
    service = CompanyService(db)
    companies, total = service.get_companies(
        skip=skip, limit=limit, is_active=is_active
    )
    return {"total": total, "skip": skip, "limit": limit, "data": companies}


@router.get("/{company_id}", response_model=CompanyResponse)
def get_company(
    company_id: UUID,
    db: Session = Depends(get_db),
    _: dict = Depends(RequireRole(["platform_admin"])),
):
    """Get a single company by ID. Admin only."""
    service = CompanyService(db)
    try:
        return service.get_company_by_id(company_id)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=e.message)


@router.patch("/{company_id}", response_model=CompanyResponse)
def update_company(
    company_id: UUID,
    company_in: CompanyUpdate,
    db: Session = Depends(get_db),
    _: dict = Depends(RequireRole(["platform_admin"])),
):
    """Update a company. Admin only."""
    service = CompanyService(db)
    try:
        company = service.update_company(company_id, company_in)
        db.commit()
        return company
    except ResourceNotFoundError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=e.message)
    except Exception as e:
        db.rollback()
        raise e
