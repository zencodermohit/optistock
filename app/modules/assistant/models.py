"""A thing the assistant thinks should happen, which has not happened.

The assistant reads. When it decides something ought to be ordered, it writes a
row here and stops. Nothing downstream watches this table; no worker drains it.
The only way a proposal becomes a purchase order is a person opening the screen
and clicking approve, and that path runs the same PurchaseOrderService a human
uses from the Purchase Orders page.

That gap is the design. A model that can place orders is one confused inference
away from ordering forty thousand units, and no amount of prompt engineering
turns "usually correct" into "safe to leave alone with a budget". Splitting
the decision from the execution means the model can be wrong at no cost, which
is the only assumption about a language model that has held up.

The table doubles as the audit trail, and the two payload columns are why:

    proposed_payload   what the model asked for
    executed_payload   what the human actually ran

They are separate columns rather than one, because an approver who changes 200
units to 50 is telling you something about the model that a single overwritten
field would erase. Comparing the two over time is how you find out whether the
suggestions are worth reading.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.core.database import Base

#: The only action the assistant may propose today. An enumeration rather than
#: a free string, so adding a second one is a deliberate act with a migration
#: attached rather than a new value appearing in production.
ACTION_CREATE_PURCHASE_ORDER = "purchase_order.create"
ACTION_TYPES = (ACTION_CREATE_PURCHASE_ORDER,)

STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"  # approved and executed successfully
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"  # approved, but execution did not succeed
STATUS_EXPIRED = "expired"

#: How long a proposal stays actionable. A reorder suggestion is built on stock
#: levels at a moment; approving it a week later executes a decision made
#: against numbers that no longer exist. Expiring is the honest default -- the
#: model can always propose it again from current data.
PROPOSAL_TTL = timedelta(hours=24)


def _expiry() -> datetime:
    return datetime.now(timezone.utc) + PROPOSAL_TTL


class AssistantAction(Base):
    """One proposal, its decision, and the difference between them."""

    __tablename__ = "assistant_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Carried on the row rather than derived through the user, for the same
    # reason audit_logs does it: decided_by_user_id is ON DELETE SET NULL, and
    # deleting a user must not orphan the tenancy of their approvals.
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )

    action_type = Column(String(50), nullable=False)
    status = Column(String(20), default=STATUS_PROPOSED, nullable=False)

    #: What the model asked for. Never mutated after insert.
    proposed_payload = Column(JSONB, nullable=False)
    #: What was actually executed. NULL until approval, and deliberately allowed
    #: to differ from the proposal.
    executed_payload = Column(JSONB, nullable=True)

    #: The model's stated reason, and the question that produced it. Kept so a
    #: proposal can be judged months later without reconstructing the session.
    rationale = Column(Text, nullable=True)
    source_question = Column(Text, nullable=True)
    proposed_by_model = Column(String(100), nullable=True)

    #: Who asked. Distinct from who approved -- often the same person, but the
    #: audit trail should not assume it.
    requested_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by_user_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    proposed_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at = Column(DateTime(timezone=True), default=_expiry, nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=True)

    #: The purchase order this became, once it became one.
    result_id = Column(UUID(as_uuid=True), nullable=True)
    #: Why execution failed, if it did. A failed approval must not look like a
    #: rejected one -- the person clicked yes.
    error = Column(Text, nullable=True)

    __table_args__ = (
        # The approvals screen's only query: this company's proposals, newest
        # first, usually filtered to the ones still awaiting a decision.
        Index(
            "ix_assistant_actions_company_status",
            "company_id",
            "status",
            "proposed_at",
        ),
    )

    @property
    def is_actionable(self) -> bool:
        if self.status != STATUS_PROPOSED:
            return False
        expires = self.expires_at
        if expires is None:
            return True
        # Rows read back from Postgres carry a timezone; ones just constructed
        # in Python may not, and comparing the two raises.
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        return expires > datetime.now(timezone.utc)
