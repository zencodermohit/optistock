"""Telling somebody an alert happened.

The EmailService interface and its mock had existed for months with no caller,
which made the alerting requirement a design document rather than a feature.
These tests cover the caller, and most of them are about what it refuses to do:
notify for a warning, notify twice for a de-duplicated alert, or take an alert
down with it when the mail server is unreachable.
"""


from app.core.notifications import EmailService
from app.modules.alerts import notifications
from app.modules.alerts.service import TYPE_LOW_STOCK, TYPE_OUT_OF_STOCK, AlertService
from app.modules.alerts.models import Alert, STATUS_OPEN


class Recorder(EmailService):
    """Captures what would have been sent."""

    def __init__(self):
        self.sent = []

    def send_email(self, to_address: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to_address, "subject": subject, "body": body})
        return True


class Broken(EmailService):
    def send_email(self, to_address: str, subject: str, body: str) -> bool:
        raise RuntimeError("smtp unreachable")


def _raise(db, company, severity="critical", **overrides):
    return AlertService(db).open_alert(
        company_id=company.id,
        alert_type=overrides.get("alert_type", TYPE_OUT_OF_STOCK),
        severity=severity,
        subject_type="inventory",
        subject_id=overrides.get("subject_id", company.id),
        title=overrides.get("title", "Widget is out of stock"),
        detail=overrides.get("detail", {"quantity": 0, "reorder_point": 20}),
    )


def test_a_critical_alert_reaches_the_people_who_can_act_on_it(
    db_session, company, admin_user
):
    alert = _raise(db_session, company)
    recorder = Recorder()

    sent = notifications.notify_critical(db_session, alert, service=recorder)

    assert sent == 1
    assert recorder.sent[0]["to"] == admin_user.email
    assert "Critical" in recorder.sent[0]["subject"]
    assert "out of stock" in recorder.sent[0]["subject"]


def test_a_warning_does_not_email_anyone(db_session, company, admin_user):
    """An alert channel people learn to filter is worse than none, because it
    looks like coverage."""
    alert = _raise(db_session, company, severity="warning", alert_type=TYPE_LOW_STOCK)
    recorder = Recorder()

    assert notifications.notify_critical(db_session, alert, service=recorder) == 0
    assert recorder.sent == []


def test_the_email_carries_the_evidence(db_session, company, admin_user):
    """Actionable from the notification alone. A warning you cannot check is a
    warning you learn to ignore."""
    alert = _raise(
        db_session, company, detail={"quantity": 0, "reorder_point": 20}
    )
    recorder = Recorder()

    notifications.notify_critical(db_session, alert, service=recorder)
    body = recorder.sent[0]["body"]

    assert "Severity: critical" in body
    assert "reorder_point: 20" in body


def test_only_active_users_in_the_right_roles_are_notified(
    db_session, company, admin_user
):
    from app.modules.users.models import User
    from app.core.security import get_password_hash

    db_session.add_all(
        [
            User(
                company_id=company.id,
                email="analyst-notify@technova.com",
                hashed_password=get_password_hash("x"),
                role="analyst",  # read-only: cannot act on it
                is_active=True,
            ),
            User(
                company_id=company.id,
                email="former@technova.com",
                hashed_password=get_password_hash("x"),
                role="admin",
                is_active=False,  # gone
            ),
        ]
    )
    db_session.flush()

    addresses = notifications.recipients_for(db_session, company.id)

    assert admin_user.email in addresses
    assert "analyst-notify@technova.com" not in addresses
    assert "former@technova.com" not in addresses


def test_another_tenants_staff_are_never_notified(
    db_session, company, other_company, admin_user, other_admin_user
):
    alert = _raise(db_session, company)
    recorder = Recorder()

    notifications.notify_critical(db_session, alert, service=recorder)

    assert [m["to"] for m in recorder.sent] == [admin_user.email]
    assert other_admin_user.email not in [m["to"] for m in recorder.sent]


def test_an_unreachable_mail_server_does_not_lose_the_alert(
    db_session, company, admin_user, monkeypatch
):
    """The alert is the durable record; the email is a courtesy.

    This is the property that matters most: a consumer raising a stockout alert
    must not have its transaction rolled back because SMTP was down.
    """
    monkeypatch.setattr(notifications, "get_email_service", lambda: Broken())

    alert = _raise(db_session, company)
    db_session.commit()

    assert alert is not None
    stored = (
        db_session.query(Alert)
        .filter(Alert.company_id == company.id, Alert.status == STATUS_OPEN)
        .all()
    )
    assert len(stored) == 1


def test_a_deduplicated_alert_does_not_notify_twice(
    db_session, company, admin_user, monkeypatch
):
    """open_alert returns None when an identical alert is already open, and the
    second attempt must be as silent as it is inert -- otherwise a flapping
    condition emails somebody every few seconds."""
    recorder = Recorder()
    monkeypatch.setattr(notifications, "get_email_service", lambda: recorder)

    first = _raise(db_session, company, subject_id=company.id)
    second = _raise(db_session, company, subject_id=company.id)

    assert first is not None
    assert second is None
    assert len(recorder.sent) == 1


def test_no_recipients_is_survivable(db_session, other_company):
    """A company with nobody in a responding role should log and move on rather
    than raise into a consumer."""
    alert = AlertService(db_session).open_alert(
        company_id=other_company.id,
        alert_type=TYPE_OUT_OF_STOCK,
        severity="critical",
        subject_type="inventory",
        subject_id=other_company.id,
        title="Nobody is listening",
        detail={},
    )
    recorder = Recorder()

    assert notifications.notify_critical(db_session, alert, service=recorder) == 0


def test_notifying_on_nothing_is_a_no_op(db_session):
    assert notifications.notify_critical(db_session, None) == 0
