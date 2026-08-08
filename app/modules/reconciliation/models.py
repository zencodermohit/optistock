import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Reconciliation(Base):
    __tablename__ = "reconciliations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    # status: pending, approved, rejected
    status = Column(String(50), default="pending", nullable=False)

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    # In a real app with Auth, you would also track 'created_by_user_id' and 'approved_by_user_id'

    from sqlalchemy.orm import relationship

    items = relationship("ReconciliationItem", back_populates="reconciliation")


class ReconciliationItem(Base):
    __tablename__ = "reconciliation_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    reconciliation_id = Column(
        UUID(as_uuid=True), ForeignKey("reconciliations.id"), index=True, nullable=False
    )
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True, nullable=False
    )

    expected_quantity = Column(Integer, nullable=False)
    actual_quantity = Column(Integer, nullable=False)

    # Reason code: e.g., "damaged", "lost", "data_entry_error"
    discrepancy_reason = Column(String(255))

    from sqlalchemy.orm import relationship

    reconciliation = relationship("Reconciliation", back_populates="items")
