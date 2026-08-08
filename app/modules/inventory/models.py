import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    DateTime,
    ForeignKey,
    CheckConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Inventory(Base):
    __tablename__ = "inventory"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True, nullable=False
    )
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    # DB-level protection against negative stock
    quantity = Column(
        Integer,
        CheckConstraint("quantity >= 0", name="check_qty_non_negative"),
        nullable=False,
        default=0,
    )
    last_counted_at = Column(DateTime(timezone=True), default=datetime.utcnow)

    # Threshold that fires a low-stock alert. Lives here rather than on Product
    # because (product, warehouse) is the grain at which the question "am I low
    # on stock?" is actually asked — a busy warehouse needs a bigger buffer than
    # a quiet one. 0 means "not configured", so nothing alerts until someone
    # sets a real number.
    reorder_point = Column(
        Integer,
        CheckConstraint(
            "reorder_point >= 0", name="ck_inventory_reorder_point_non_negative"
        ),
        nullable=False,
        default=0,
        server_default="0",
    )

    __table_args__ = (
        UniqueConstraint("product_id", "warehouse_id", name="uix_product_warehouse"),
    )


class InventoryMovement(Base):
    __tablename__ = "inventory_movements"

    # The Immutable Ledger
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    inventory_id = Column(
        UUID(as_uuid=True), ForeignKey("inventory.id"), index=True, nullable=False
    )

    movement_type = Column(
        String(50), nullable=False
    )  # e.g., 'sale', 'po_delivery', 'adjustment'
    quantity_change = Column(Integer, nullable=False)  # Can be negative
    quantity_after = Column(Integer, nullable=False)

    reference_id = Column(
        String(255)
    )  # Connects movement to an external ID (like a PO number)

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
