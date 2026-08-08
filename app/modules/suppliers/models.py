import uuid
from sqlalchemy import Column, String, Numeric, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Supplier(Base):
    __tablename__ = "suppliers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    name = Column(String(255), nullable=False)
    contact_email = Column(String(255))

    # Notice this! We will use this in Stage 7 for Machine Learning.
    # It tracks how often the supplier is late.
    reliability_score = Column(Numeric(3, 2), default=1.0)

    is_active = Column(Boolean, default=True, nullable=False)
