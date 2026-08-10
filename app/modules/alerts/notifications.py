"""Telling somebody an alert happened.

The alerting requirement was the one part of the spec with nothing behind it:
`app/core/notifications.py` defined an EmailService interface and a mock, and
nothing in the application ever called either. An interface with no callers is
a design document, not a feature.

This is the caller. Two decisions shape it:

**Only critical.** A warning is something to look at when you next open the
app; a critical alert is something that has already gone wrong. Emailing both
would train the recipient to filter the address, and an alert channel people
filter is worse than no alert channel, because it looks like coverage.

**Never breaks the alert.** The notification runs after the alert row is
written and every failure inside it is swallowed and logged. An unreachable
mail server must not roll back a consumer's transaction and lose the alert
itself -- the alert is the durable record, the email is a courtesy.

The transport is still the mock, which logs instead of sending. That is a
deployment decision (nobody has bought an SMTP credential) rather than a gap in
the wiring: swapping `get_email_service` for a real implementation is the one
line it was always designed to be, and everything above this comment stays put.
"""

import logging
from typing import List
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.notifications import EmailService, get_email_service
from app.modules.alerts.models import Alert
from app.modules.users.models import User

logger = logging.getLogger(__name__)

#: Who hears about a critical alert. Roles rather than a mailing list, so the
#: recipients follow the org chart instead of drifting out of date in a config
#: file nobody owns.
NOTIFY_ROLES = ("admin", "supply_chain", "warehouse_manager")

SEVERITY_CRITICAL = "critical"


def recipients_for(db: Session, company_id: UUID) -> List[str]:
    """Active users in this company whose job is to act on stock trouble."""
    rows = (
        db.query(User.email)
        .filter(
            User.company_id == company_id,
            User.is_active.is_(True),
            User.role.in_(NOTIFY_ROLES),
        )
        .all()
    )
    return [email for (email,) in rows if email]


def _body(alert: Alert) -> str:
    """The email, written to be actionable from the notification alone.

    Somebody reading this on a phone should know what is wrong and how bad it
    is without opening anything. The evidence the alert carries is included for
    the same reason it is shown on screen: a warning you cannot check is a
    warning you learn to ignore.
    """
    lines = [
        alert.title,
        "",
        f"Severity: {alert.severity}",
        f"Raised: {alert.created_at:%Y-%m-%d %H:%M UTC}"
        if alert.created_at
        else "Raised: just now",
    ]
    if alert.detail:
        lines.append("")
        lines.append("What triggered it:")
        lines.extend(f"  {key}: {value}" for key, value in alert.detail.items())
    lines.extend(["", "Open OptiStock to see the current position."])
    return "\n".join(lines)


def notify_critical(
    db: Session, alert: Alert, service: EmailService | None = None
) -> int:
    """Send one alert to the people who can act on it. Returns how many were sent.

    Returns 0 rather than raising for every unhappy path -- not critical, no
    recipients, transport down. The caller is a consumer in the middle of a
    transaction and has nothing useful to do with an exception from here.
    """
    if alert is None or alert.severity != SEVERITY_CRITICAL:
        return 0

    try:
        addresses = recipients_for(db, alert.company_id)
    except Exception:
        logger.exception(
            "alerts.notify_lookup_failed", extra={"alert_id": str(alert.id)}
        )
        return 0

    if not addresses:
        logger.warning(
            "alerts.no_recipients",
            extra={"company_id": str(alert.company_id), "alert_id": str(alert.id)},
        )
        return 0

    service = service or get_email_service()
    subject = f"[OptiStock] Critical: {alert.title}"
    body = _body(alert)

    sent = 0
    for address in addresses:
        try:
            if service.send_email(address, subject, body):
                sent += 1
        except Exception:
            # One bad address must not cost the others their notification.
            logger.exception(
                "alerts.notify_failed",
                extra={"alert_id": str(alert.id), "recipient": address},
            )

    logger.info(
        "alerts.notified",
        extra={
            "alert_id": str(alert.id),
            "alert_type": alert.alert_type,
            "recipients": len(addresses),
            "sent": sent,
        },
    )
    return sent
