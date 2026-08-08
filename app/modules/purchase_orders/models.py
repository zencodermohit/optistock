import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Numeric, DateTime, ForeignKey, Date
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    # Foreign Keys linking modules together!
    supplier_id = Column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), index=True, nullable=False
    )
    destination_warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    # Lifecycle states (draft, submitted, delivered, cancelled)
    status = Column(String(50), default="draft", nullable=False)

    expected_delivery_date = Column(Date)
    total_amount = Column(Numeric(12, 2), default=0.0)

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Enable ORM navigation: po.items
    from sqlalchemy.orm import relationship

    items = relationship("POItem", back_populates="po")


class POItem(Base):
    __tablename__ = "po_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    po_id = Column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), index=True, nullable=False
    )
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True, nullable=False
    )

    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(12, 2), nullable=False)

    from sqlalchemy.orm import relationship

    po = relationship("PurchaseOrder", back_populates="items")
