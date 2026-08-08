import uuid

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base


class EventOutbox(Base):
    """A domain event, written in the same transaction as the change it describes.

    This is the transactional outbox. Nothing publishes to the message queue
    from inside a request — a row is inserted here instead, and a separate relay
    process picks it up. That makes the change and its event atomic: either both
    are committed or neither is.
    """

    __tablename__ = "event_outbox"

    # Gap-free insertion order. Replay depends on a sortable key, which a random
    # UUID primary key cannot provide.
    sequence = Column(BigInteger, primary_key=True, autoincrement=True)

    # Stable public identifier. Consumers de-duplicate on this, because
    # at-least-once delivery means the same event can arrive twice.
    event_id = Column(UUID(as_uuid=True), default=uuid.uuid4, nullable=False)

    # Tenant carried on the event itself, so a consumer never needs a database
    # lookup to know which company an event belongs to.
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    event_type = Column(String(100), nullable=False)  # 'stock.deducted'
    aggregate_type = Column(String(50), nullable=False)  # 'inventory'
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)

    payload = Column(JSONB, nullable=False)

    actor_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    occurred_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NULL until the relay has published it. This one nullable column is the
    # entire publish state machine, and the partial index on it keeps the
    # relay's query fast however large the table grows.
    published_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("event_id", name="uq_event_outbox_event_id"),)
