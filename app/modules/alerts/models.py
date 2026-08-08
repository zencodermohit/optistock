import uuid

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base

# Kept as module constants so consumers, the API and the tests all agree on the
# vocabulary rather than each hard-coding their own strings.
STATUS_OPEN = "open"
STATUS_RESOLVED = "resolved"
STATUS_DISMISSED = "dismissed"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"


class Alert(Base):
    """Something the system noticed and thinks a human should see.

    De-duplication is enforced by a partial unique index in the database, not by
    application logic: at most one alert may be OPEN per
    (company, alert_type, subject) at a time. A stock level that stays low for a
    week therefore produces one alert, not one per inventory event.
    """

    __tablename__ = "alerts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    alert_type = Column(String(50), nullable=False)  # 'low_stock', 'overdue_po'
    severity = Column(String(20), nullable=False)
    status = Column(
        String(20), nullable=False, default=STATUS_OPEN, server_default=STATUS_OPEN
    )

    # What the alert is about, e.g. ("inventory", <inventory row id>).
    subject_type = Column(String(50), nullable=False)
    subject_id = Column(UUID(as_uuid=True), nullable=False)

    title = Column(String(255), nullable=False)
    # The evidence that fired it — same explainability contract as
    # Recommendation.evidence, so the UI can always answer "why am I seeing this?"
    detail = Column(JSONB, nullable=False)

    # Provenance: which event caused this.
    triggered_by_event_id = Column(UUID(as_uuid=True), nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Resolved = the condition cleared on its own. Dismissed = a human waved it
    # away. Worth distinguishing: one is the system being right, the other is a
    # signal the alert was noise.
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_at = Column(DateTime(timezone=True), nullable=True)
    dismissed_by = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')", name="ck_alerts_status"
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name="ck_alerts_severity"
        ),
    )
