import uuid
from datetime import datetime
from sqlalchemy import Column, String, Numeric, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)

    # Multi-tenant foreign key linking to the companies table we just made
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    # Indexed but NOT globally unique: uniqueness is per tenant, enforced by the
    # composite constraint in __table_args__ below.
    sku = Column(String(50), index=True, nullable=False)
    name = Column(String(255), nullable=False)
    category = Column(String(100))

    # Financials (Always use Numeric for money!)
    unit_cost = Column(Numeric(12, 2), nullable=False)
    selling_price = Column(Numeric(12, 2), nullable=False)

    # Lifecycle state (active, archived, discontinued)
    status = Column(String(20), default="active", nullable=False)

    # Written by the nightly ABC analysis. Nullable because a product has no
    # class until it has appeared in a completed sale.
    abc_class = Column(String(1))
    abc_calculated_at = Column(DateTime(timezone=True))

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uix_product_company_sku"),
    )
