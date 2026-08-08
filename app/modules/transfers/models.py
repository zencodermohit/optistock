import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Transfer(Base):
    __tablename__ = "transfers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    source_warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )
    destination_warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    # Lifecycle: pending, in_transit, completed, cancelled
    status = Column(String(50), default="pending", nullable=False)

    shipped_at = Column(DateTime(timezone=True))
    received_at = Column(DateTime(timezone=True))

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    from sqlalchemy.orm import relationship

    items = relationship("TransferItem", back_populates="transfer")


class TransferItem(Base):
    __tablename__ = "transfer_items"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    transfer_id = Column(
        UUID(as_uuid=True), ForeignKey("transfers.id"), index=True, nullable=False
    )
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True, nullable=False
    )

    quantity = Column(Integer, nullable=False)

    from sqlalchemy.orm import relationship

    transfer = relationship("Transfer", back_populates="items")
