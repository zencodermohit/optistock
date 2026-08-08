"""Brute-force and enumeration defences on the login endpoint.

Login is the one endpoint where guessing pays off, and it previously had none of
these: no rate limit (the blanket 10 req/s at the proxy allowed 600 password
attempts per minute per address), no lockout, and a failure path whose duration
revealed whether an email address was registered.
"""

import time
from datetime import datetime, timedelta, timezone

from app.core.security import get_password_hash
from app.modules.users.models import User
from app.modules.users.router import LOCKOUT_DURATION, MAX_FAILED_ATTEMPTS

PASSWORD = "a-sufficiently-long-password"


def _login(client, email, password=PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


def test_valid_credentials_return_a_token(client, admin_user):
    response = _login(client, admin_user.email)

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_wrong_password_is_rejected(client, admin_user):
    response = _login(client, admin_user.email, "definitely-the-wrong-password")

    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"


def test_unknown_email_gives_the_same_message_as_a_wrong_password(client, admin_user):
    """The two failures must be indistinguishable to the caller."""
    unknown = _login(client, "nobody@example.org")
    wrong = _login(client, admin_user.email, "wrong")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


# ---------------------------------------------------------------------------
# Lockout
# ---------------------------------------------------------------------------
def test_repeated_failures_lock_the_account(client, db_session, admin_user):
    for _ in range(MAX_FAILED_ATTEMPTS):
        assert _login(client, admin_user.email, "wrong").status_code == 401

    db_session.expire_all()
    assert admin_user.failed_login_attempts == MAX_FAILED_ATTEMPTS
    assert admin_user.locked_until is not None

    # Even the CORRECT password is refused while the lock stands.
    locked = _login(client, admin_user.email)
    assert locked.status_code == 429
    assert "locked" in locked.json()["detail"].lower()


def test_an_expired_lock_lets_the_user_back_in(client, db_session, admin_user):
    admin_user.failed_login_attempts = MAX_FAILED_ATTEMPTS
    admin_user.locked_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()

    response = _login(client, admin_user.email)

    assert response.status_code == 200
    db_session.expire_all()
    assert admin_user.failed_login_attempts == 0
    assert admin_user.locked_until is None


def test_a_successful_login_clears_the_failure_counter(client, db_session, admin_user):
    for _ in range(MAX_FAILED_ATTEMPTS - 1):
        _login(client, admin_user.email, "wrong")

    db_session.expire_all()
    assert admin_user.failed_login_attempts == MAX_FAILED_ATTEMPTS - 1

    assert _login(client, admin_user.email).status_code == 200

    db_session.expire_all()
    assert admin_user.failed_login_attempts == 0


def test_lockout_is_per_account_not_global(client, db_session, company, admin_user):
    """One user being locked out must not deny service to their colleagues."""
    colleague = User(
        email="colleague@example.com",
        hashed_password=get_password_hash(PASSWORD),
        company_id=company.id,
        role="analyst",
        is_active=True,
    )
    db_session.add(colleague)
    db_session.commit()

    for _ in range(MAX_FAILED_ATTEMPTS):
        _login(client, admin_user.email, "wrong")

    assert _login(client, admin_user.email).status_code == 429
    assert _login(client, colleague.email).status_code == 200


def test_lockout_duration_is_configured_sensibly():
    assert LOCKOUT_DURATION >= timedelta(minutes=5)
    assert MAX_FAILED_ATTEMPTS <= 10


# ---------------------------------------------------------------------------
# Timing side channel
# ---------------------------------------------------------------------------
def test_unknown_email_takes_comparable_time_to_a_wrong_password(client, admin_user):
    """Short-circuiting on an unknown email skipped the bcrypt comparison, so
    "no such user" returned in ~1ms and "wrong password" in ~200ms. That gap lets
    an attacker harvest valid addresses — precisely the list a credential
    stuffing run needs.
    """

    def elapsed(email):
        start = time.perf_counter()
        _login(client, email, "some-wrong-password")
        return time.perf_counter() - start

    # Warm up so first-call import/JIT costs do not skew the comparison.
    elapsed(admin_user.email)

    unknown = min(elapsed("nobody@example.org") for _ in range(3))
    known = min(elapsed(admin_user.email) for _ in range(3))

    # Both paths run a real bcrypt verification, so neither should be an order of
    # magnitude faster. Generous bound: this asserts "no short circuit", not a
    # constant-time guarantee.
    assert unknown > known / 3, (
        f"unknown-email path was suspiciously fast: {unknown:.4f}s vs {known:.4f}s"
    )


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
def test_login_is_rate_limited(client, admin_user, enforced_rate_limiting):
    """Without a limit the proxy's blanket 10 req/s allowed 600 guesses a minute."""
    statuses = [
        _login(client, "nobody@example.org", "wrong").status_code for _ in range(8)
    ]

    assert 429 in statuses, f"expected throttling, got {statuses}"
    assert statuses.index(429) <= 6, f"limit kicked in too late: {statuses}"


def test_rate_limit_does_not_apply_to_unrelated_endpoints(
    authenticated_client, enforced_rate_limiting
):
    statuses = [
        authenticated_client.get("/api/v1/products/").status_code for _ in range(12)
    ]
    assert statuses == [200] * 12
