import uuid
from sqlalchemy import (
    Column,
    String,
    Integer,
    Boolean,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Warehouse(Base):
    __tablename__ = "warehouses"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    name = Column(String(255), nullable=False)
    # Indexed but NOT globally unique: uniqueness is per tenant, enforced by the
    # composite constraint in __table_args__ below.
    location_code = Column(String(50), index=True, nullable=False)
    capacity_units = Column(Integer, nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "company_id", "location_code", name="uix_warehouse_company_location"
        ),
    )
