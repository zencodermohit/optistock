import uuid
from datetime import datetime
from sqlalchemy import Column, String, Boolean, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    email = Column(String(255), unique=True, index=True, nullable=False)

    # NEVER store plaintext passwords. We store the bcrypt hash.
    hashed_password = Column(String(255), nullable=False)

    # The RBAC Role: "admin", "finance", "supply_chain", or "analyst"
    role = Column(String(50), nullable=False)

    is_active = Column(Boolean, default=True, nullable=False)

    # Brute-force lockout state. Reset on every successful authentication.
    failed_login_attempts = Column(
        Integer, default=0, server_default="0", nullable=False
    )
    locked_until = Column(DateTime(timezone=True))

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
