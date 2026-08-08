from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
import uuid
from app.core.database import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    # Tenant is stored directly rather than derived through user_id. user_id is
    # ON DELETE SET NULL, so joining through it meant deleting a user erased the
    # readability of their entire audit trail.
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )
    entity_name = Column(String, index=True, nullable=False)  # e.g. "products", "sales"
    entity_id = Column(
        UUID(as_uuid=True), index=True, nullable=False
    )  # ID of the product or sale
    action = Column(String, index=True, nullable=False)  # "CREATE", "UPDATE", "DELETE"
    old_values = Column(JSON, nullable=True)
    new_values = Column(JSON, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
