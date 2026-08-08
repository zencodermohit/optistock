import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    product_id = Column(
        UUID(as_uuid=True), ForeignKey("products.id"), index=True, nullable=False
    )
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    suggested_action = Column(
        String(50), nullable=False
    )  # e.g., "reorder", "transfer", "discount"
    suggested_quantity = Column(Integer, nullable=False)

    # EXPLAINABILITY: The "Why" behind the AI's decision
    confidence_score = Column(Integer, nullable=False)  # 1-100 scale

    # We use a JSON column to store variable evidence (e.g. {"demand_spike": "+20%", "lead_time_risk": "high"})
    evidence = Column(JSON, nullable=False)

    business_reasoning = Column(String(500), nullable=False)

    # Who produced this row. The nightly forecast replaces its OWN previous
    # output on each run so results stay idempotent; without this column it
    # could not tell its own rows apart from ones a human created, and would
    # either delete their work or duplicate its own forever.
    source = Column(
        String(50), nullable=False, default="manual", server_default="manual"
    )

    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
