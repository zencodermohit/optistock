from sqlalchemy.orm import Session
from uuid import UUID
from typing import List, Tuple, Optional

from app.modules.companies.models import Company
from app.modules.companies.schemas import CompanyCreate, CompanyUpdate
from app.core.exceptions import ResourceNotFoundError


class CompanyService:
    def __init__(self, db: Session):
        self.db = db

    def get_companies(
        self, skip: int = 0, limit: int = 50, is_active: Optional[bool] = None
    ) -> Tuple[List[Company], int]:
        query = self.db.query(Company)
        if is_active is not None:
            query = query.filter(Company.is_active == is_active)
        total = query.count()
        companies = query.offset(skip).limit(limit).all()
        return companies, total

    def get_company_by_id(self, company_id: UUID) -> Company:
        company = self.db.query(Company).filter(Company.id == company_id).first()
        if not company:
            raise ResourceNotFoundError("Company", str(company_id))
        return company

    def create_company(self, company_in: CompanyCreate) -> Company:
        company = Company(name=company_in.name, is_active=True)
        self.db.add(company)
        self.db.flush()
        return company

    def update_company(self, company_id: UUID, company_in: CompanyUpdate) -> Company:
        company = self.get_company_by_id(company_id)
        update_data = company_in.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(company, key, value)
        self.db.flush()
        return company
