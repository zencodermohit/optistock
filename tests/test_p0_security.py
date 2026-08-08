from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.dependencies import RequireRole, get_current_user
from app.core.security import create_access_token
from app.modules.products.schemas import ProductCreate
from app.modules.users.schemas import UserCreate
from app.modules.warehouses.schemas import WarehouseCreate


class FakeQuery:
    def __init__(self, user):
        self.user = user

    def filter(self, *_args):
        return self

    def first(self):
        return self.user


class FakeDb:
    def __init__(self, user):
        self.user = user
        # get_current_user tags the session with the acting identity so the audit
        # listener can attribute downstream changes; a real Session always has
        # this dict.
        self.info = {}

    def query(self, *_args):
        return FakeQuery(self.user)


def test_current_user_uses_active_database_identity():
    user_id = uuid4()
    company_id = uuid4()
    token = create_access_token(
        {"sub": str(user_id), "role": "analyst", "company_id": str(company_id)}
    )
    db_user = SimpleNamespace(
        id=user_id, company_id=company_id, role="warehouse_manager", is_active=True
    )

    identity = get_current_user(token=token, db=FakeDb(db_user))

    assert identity == {
        "id": str(user_id),
        "role": "warehouse_manager",
        "company_id": str(company_id),
    }


def test_current_user_rejects_legacy_token_without_tenant_claim():
    token = create_access_token({"sub": str(uuid4()), "role": "admin"})

    with pytest.raises(HTTPException, match="Invalid token payload"):
        get_current_user(token=token, db=FakeDb(None))


def test_inactive_user_cannot_use_an_otherwise_valid_token():
    user_id = uuid4()
    company_id = uuid4()
    token = create_access_token(
        {"sub": str(user_id), "role": "admin", "company_id": str(company_id)}
    )
    db_user = SimpleNamespace(
        id=user_id, company_id=company_id, role="admin", is_active=False
    )

    with pytest.raises(HTTPException, match="Inactive or unknown user"):
        get_current_user(token=token, db=FakeDb(db_user))


def test_registration_payload_cannot_choose_a_tenant_or_unknown_role():
    with pytest.raises(ValidationError):
        UserCreate(
            email="worker@example.com",
            password="a-secure-password",
            company_id=str(uuid4()),
        )
    with pytest.raises(ValidationError):
        UserCreate(
            email="worker@example.com",
            password="a-secure-password",
            role="superuser",
        )


def test_product_and_warehouse_payloads_cannot_set_company_id():
    with pytest.raises(ValidationError):
        ProductCreate(
            sku="SKU-001",
            name="Example",
            unit_cost=10,
            selling_price=15,
            company_id=str(uuid4()),
        )
    with pytest.raises(ValidationError):
        WarehouseCreate(
            name="Main Warehouse",
            location_code="MAIN",
            capacity_units=100,
            company_id=str(uuid4()),
        )


def test_role_guard_blocks_unapproved_role():
    with pytest.raises(HTTPException) as exc:
        RequireRole(["admin"])({"role": "analyst"})

    assert exc.value.status_code == 403
