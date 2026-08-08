"""Customer management.

The Customer model itself lives in ``app.modules.sales.models`` because Sale
holds a foreign key to it and they were created in the same migration. Only the
API surface lives here — moving the table would mean rewriting migrations for no
functional gain.
"""

from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.exceptions import ResourceNotFoundError
from app.modules.customers.schemas import CustomerCreate, CustomerUpdate
from app.modules.sales.models import Customer, Sale


class CustomerService:
    """Transaction boundary rule: stage with flush(), never commit.
    The router owns the transaction. Same rule as every other service here."""

    def __init__(self, db: Session):
        self.db = db

    def get_customers(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        search: Optional[str] = None,
        is_active: Optional[bool] = None,
    ) -> Tuple[List[Customer], int]:
        query = self.db.query(Customer).filter(Customer.company_id == company_id)

        if search:
            pattern = f"%{search}%"
            query = query.filter(
                Customer.name.ilike(pattern) | Customer.email.ilike(pattern)
            )
        if is_active is not None:
            query = query.filter(Customer.is_active == is_active)

        total = query.count()
        customers = query.order_by(Customer.name).offset(skip).limit(limit).all()
        return customers, total

    def get_customer_by_id(self, customer_id: UUID, company_id: UUID) -> Customer:
        customer = (
            self.db.query(Customer)
            .filter(Customer.id == customer_id, Customer.company_id == company_id)
            .first()
        )
        if not customer:
            # 404 rather than 403: we must not confirm that an id exists in
            # another tenant.
            raise ResourceNotFoundError(
                resource="Customer", resource_id=str(customer_id)
            )
        return customer

    def create_customer(
        self, customer_in: CustomerCreate, company_id: UUID
    ) -> Customer:
        customer = Customer(
            company_id=company_id,
            name=customer_in.name,
            email=customer_in.email,
            is_active=True,
        )
        self.db.add(customer)
        self.db.flush()
        return customer

    def update_customer(
        self, customer_id: UUID, customer_in: CustomerUpdate, company_id: UUID
    ) -> Customer:
        customer = self.get_customer_by_id(customer_id, company_id)

        # exclude_unset so an omitted field is left alone rather than nulled.
        for field, value in customer_in.model_dump(exclude_unset=True).items():
            setattr(customer, field, value)

        self.db.flush()
        return customer

    def deactivate_customer(self, customer_id: UUID, company_id: UUID) -> Customer:
        """Soft delete. Sales reference customers, so hard deletion would either
        break history or cascade it away — neither is acceptable in a system
        whose whole point is an accurate record."""
        customer = self.get_customer_by_id(customer_id, company_id)
        customer.is_active = False
        self.db.flush()
        return customer

    def get_customer_orders(
        self, customer_id: UUID, company_id: UUID, skip: int = 0, limit: int = 50
    ) -> Tuple[List[Sale], int, float]:
        """Order history plus lifetime value, for the customer detail screen."""
        self.get_customer_by_id(customer_id, company_id)  # 404s if not ours

        query = self.db.query(Sale).filter(
            Sale.customer_id == customer_id, Sale.company_id == company_id
        )
        total = query.count()

        lifetime_value = (
            self.db.query(func.coalesce(func.sum(Sale.total_amount), 0))
            .filter(
                Sale.customer_id == customer_id,
                Sale.company_id == company_id,
                Sale.status == "completed",
            )
            .scalar()
        )

        orders = query.order_by(Sale.created_at.desc()).offset(skip).limit(limit).all()
        return orders, total, float(lifetime_value or 0)
