from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import OptiStockException, ResourceNotFoundError
from app.modules.alerts.models import (
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    STATUS_DISMISSED,
    STATUS_OPEN,
    STATUS_RESOLVED,
    Alert,
)

# Alert types, in one place so handlers, the API and the UI agree.
TYPE_LOW_STOCK = "low_stock"
TYPE_OUT_OF_STOCK = "out_of_stock"

ALL_ALERT_TYPES = frozenset({TYPE_LOW_STOCK, TYPE_OUT_OF_STOCK})

# Severity is stored as a word, which does not sort by urgency -- alphabetically
# "critical" happens to come first but "info" sorts above "warning", which is
# backwards. Ranked explicitly rather than relying on that accident.
_SEVERITY_RANK = case(
    {SEVERITY_CRITICAL: 0, SEVERITY_WARNING: 1, SEVERITY_INFO: 2},
    value=Alert.severity,
    else_=3,
)


class AlertService:
    def __init__(self, db: Session):
        self.db = db

    def open_alert(
        self,
        *,
        company_id: UUID,
        alert_type: str,
        severity: str,
        subject_type: str,
        subject_id: UUID,
        title: str,
        detail: Dict[str, Any],
        triggered_by_event_id: Optional[UUID] = None,
    ) -> Optional[Alert]:
        """Raise an alert, unless an identical one is already open.

        De-duplication is the database's job, not a prior SELECT. Two consumer
        replicas handling two events for the same product at the same instant
        would both see "no open alert" and both insert; the partial unique index
        makes the second insert fail instead. Catching that is the check.

        Returns None when the alert already existed, so callers can tell
        "raised" from "already known" without another query.
        """
        alert = Alert(
            company_id=company_id,
            alert_type=alert_type,
            severity=severity,
            status=STATUS_OPEN,
            subject_type=subject_type,
            subject_id=subject_id,
            title=title,
            detail=detail,
            triggered_by_event_id=triggered_by_event_id,
        )
        # A SAVEPOINT, so a rejected insert does not poison the surrounding
        # transaction. Without it the IntegrityError would leave the session
        # unusable and take the rest of the handler down with it.
        try:
            with self.db.begin_nested():
                self.db.add(alert)
                self.db.flush()
        except IntegrityError:
            return None
        return alert

    def resolve_matching(
        self,
        *,
        company_id: UUID,
        alert_type: str,
        subject_type: str,
        subject_id: UUID,
    ) -> int:
        """Close alerts whose condition has cleared.

        Resolved rather than dismissed: the system noticed it fixed itself. That
        distinction is what lets the alert re-open later -- the unique index
        only constrains open rows.
        """
        alerts = (
            self.db.query(Alert)
            .filter(
                Alert.company_id == company_id,
                Alert.alert_type == alert_type,
                Alert.subject_type == subject_type,
                Alert.subject_id == subject_id,
                Alert.status == STATUS_OPEN,
            )
            .all()
        )
        now = datetime.now(timezone.utc)
        for alert in alerts:
            alert.status = STATUS_RESOLVED
            alert.resolved_at = now
        self.db.flush()
        return len(alerts)

    def list_alerts(
        self,
        company_id: UUID,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> Tuple[List[Alert], int]:
        query = self.db.query(Alert).filter(Alert.company_id == company_id)

        if status:
            query = query.filter(Alert.status == status)
        if severity:
            query = query.filter(Alert.severity == severity)

        total = query.count()
        alerts = (
            # Severity first, then recency. Ordering purely by time would put a
            # minute-old warning above an hour-old stockout, and the top of a
            # triage list has to be the worst thing, not the newest thing.
            query.order_by(_SEVERITY_RANK, Alert.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return alerts, total

    def counts_by_severity(self, company_id: UUID) -> Dict[str, int]:
        """Open alerts per severity, for the badge in the navigation."""
        rows = (
            self.db.query(Alert.severity, Alert.status)
            .filter(Alert.company_id == company_id, Alert.status == STATUS_OPEN)
            .all()
        )
        counts = {"info": 0, "warning": 0, "critical": 0}
        for severity, _status in rows:
            if severity in counts:
                counts[severity] += 1
        return counts

    def dismiss(self, alert_id: UUID, company_id: UUID, user_id: UUID) -> Alert:
        """A human waved it away. Recorded as their decision, with their name.

        Kept distinct from resolved on purpose: a pile of dismissed alerts is
        evidence the rule that raised them is noisy, and collapsing the two
        states would destroy exactly the signal that says so.
        """
        alert = (
            self.db.query(Alert)
            .filter(Alert.id == alert_id, Alert.company_id == company_id)
            .first()
        )
        if not alert:
            raise ResourceNotFoundError(resource="Alert", resource_id=str(alert_id))
        if alert.status != STATUS_OPEN:
            raise OptiStockException(
                code="ALERT_NOT_OPEN",
                message=f"This alert is already {alert.status}.",
            )

        alert.status = STATUS_DISMISSED
        alert.dismissed_at = datetime.now(timezone.utc)
        alert.dismissed_by = user_id
        self.db.flush()
        return alert
