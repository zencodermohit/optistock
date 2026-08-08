"""The role vocabulary is a security boundary, so it gets tests.

The registration schema spells its roles out as a Literal so they show up in the
OpenAPI docs. That means the list exists in two places, which is exactly how the
old four-way disagreement started — hence the sync test below.
"""

import typing

import pytest
from pydantic import ValidationError

from app.core.roles import ALL_ROLES, PLATFORM_ADMIN, TENANT_ASSIGNABLE_ROLES
from app.modules.users.schemas import UserCreate

PASSWORD = "a-sufficiently-long-password"


def _schema_roles() -> set[str]:
    """The role values the registration schema actually accepts."""
    return set(typing.get_args(UserCreate.model_fields["role"].annotation))


def test_schema_matches_the_central_vocabulary():
    """If someone adds a role to one place and not the other, fail loudly."""
    assert _schema_roles() == set(TENANT_ASSIGNABLE_ROLES)


def test_platform_admin_is_not_assignable_through_registration():
    """The escalation guard.

    platform_admin reaches across tenants — it is what /companies requires for
    onboarding new companies. A tenant admin able to assign it through an
    ordinary registration call could promote themselves from customer to
    operator of the entire platform.
    """
    assert PLATFORM_ADMIN in ALL_ROLES
    assert PLATFORM_ADMIN not in TENANT_ASSIGNABLE_ROLES
    assert PLATFORM_ADMIN not in _schema_roles()

    with pytest.raises(ValidationError):
        UserCreate(email="attacker@example.com", password=PASSWORD, role=PLATFORM_ADMIN)


@pytest.mark.parametrize("role", TENANT_ASSIGNABLE_ROLES)
def test_every_tenant_role_is_accepted(role):
    assert UserCreate(email="u@example.com", password=PASSWORD, role=role).role == role


def test_unknown_roles_are_rejected():
    with pytest.raises(ValidationError):
        UserCreate(email="u@example.com", password=PASSWORD, role="superuser")


def test_registration_defaults_to_the_least_privileged_role(
    authenticated_client,
):
    """Omitting the role should not hand out a powerful one."""
    response = authenticated_client.post(
        "/api/v1/auth/register",
        json={"email": "newhire@example.com", "password": PASSWORD},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "analyst"


def test_a_tenant_admin_cannot_register_a_platform_admin(authenticated_client):
    """End to end, over HTTP — not just at the schema level."""
    response = authenticated_client.post(
        "/api/v1/auth/register",
        json={
            "email": "escalate@example.com",
            "password": PASSWORD,
            "role": PLATFORM_ADMIN,
        },
    )
    assert response.status_code == 422
