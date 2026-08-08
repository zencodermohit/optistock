import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    name = Column(String(255), nullable=False)
    email = Column(String(255))
    is_active = Column(Boolean, default=True, nullable=False)


class Sale(Base):
    __tablename__ = "sales"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    customer_id = Column(
        UUID(as_uuid=True), ForeignKey("customers.id"), index=True, nullable=False
    )
    source_warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    status = Column(String(50), default="pending", nullable=False)
    total_amount = Column(Numeric(12, 2), default=0.0)

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # SaleService.get_sales() eager-loads this with joinedload(Sale.items).
    # Without the relationship that call raises AttributeError, so every request
    # to GET /api/v1/sales/ returned a 500.
    from sqlalchemy.orm import relationship

    items = relationship("SaleItem", back_populates="sale")


class SaleItem(Base):
    __tablename__ = "sale_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    sale_id = Column(
        UUID(as_uuid=True), ForeignKey("sales.id"), index=True, nullable=False
    )
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True, nullable=False
    )

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)

    from sqlalchemy.orm import relationship

    sale = relationship("Sale", back_populates="items")
