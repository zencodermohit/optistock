"""Proposals, approvals, and the gap between them.

The gap is the feature. Everything here is really one assertion said several
ways: the model can want an order placed, and wanting it changes nothing.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.core.exceptions import OptiStockException
from app.modules.assistant import service as assistant_service
from app.modules.assistant.actions import ActionService
from app.modules.assistant.models import (
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    AssistantAction,
)
from app.modules.assistant.runtime import LLMResult, LLMRuntime
from app.modules.assistant.tools import run_tool
from app.modules.audit.models import AuditLog
from app.modules.purchase_orders.models import POItem, PurchaseOrder
from app.modules.suppliers.models import Supplier


@pytest.fixture
def supplier(db_session, company):
    record = Supplier(company_id=company.id, name="Acme Supply", is_active=True)
    db_session.add(record)
    db_session.flush()
    return record


@pytest.fixture
def orderable(db_session, company, supplier, make_product, make_warehouse, make_stock):
    """A product that can actually be ordered: costed, stocked, with a supplier."""
    product = make_product(company, sku="REORDER-1", name="Reorder widget")
    product.unit_cost = 12.50
    warehouse = make_warehouse(company)
    make_stock(product, warehouse, quantity=3)
    db_session.commit()
    return product


class Proposing(LLMRuntime):
    """A model that decides an order is needed."""

    name = "proposing"

    def __init__(self, sku="REORDER-1", quantity=100, answer="Proposed."):
        self.sku = sku
        self.quantity = quantity
        self.answer = answer
        self.result = None

    @staticmethod
    def is_configured():
        return True

    async def generate(self, *, system_prompt, history, question, tools):
        by_name = {t.__name__: t for t in tools}
        self.result = by_name["create_purchase_order"](
            sku=self.sku, quantity=self.quantity, reason="Below reorder point."
        )
        return LLMResult(text=self.answer, latency_ms=1.0)

    def describe_error(self, error):
        return "failed"


# ---------------------------------------------------------------------------
# Proposing changes nothing
# ---------------------------------------------------------------------------
def test_the_tool_creates_a_proposal_and_no_purchase_order(
    db_session, company, orderable
):
    """The whole point, in one test."""
    before = db_session.query(PurchaseOrder).count()

    result, _ = run_tool(
        db_session,
        company.id,
        "create_purchase_order",
        {"sku": "REORDER-1", "quantity": 100},
    )

    assert result["status"] == "proposed"
    assert result["requires_approval"] is True
    assert "action_id" in result
    assert db_session.query(PurchaseOrder).count() == before
    assert db_session.query(AssistantAction).count() == 1


def test_the_proposal_says_out_loud_that_nothing_happened(
    db_session, company, orderable
):
    """The message is part of the safety design, not decoration.

    It is the sentence the model reads before writing its reply, and it is what
    stops a helpful-sounding "done!" from being the last thing the user sees.
    """
    result, _ = run_tool(
        db_session, company.id, "create_purchase_order", {"sku": "REORDER-1", "quantity": 5}
    )

    assert "Nothing has been ordered" in result["message"]
    assert "approval" in result["message"].lower()


def test_a_proposal_records_which_warehouse_and_supplier_without_being_told(
    db_session, company, orderable, supplier
):
    """The model supplies a SKU and a number. Everything else is resolved from
    the tenant's own rows, so there is no field through which it could name
    another company's warehouse."""
    result, _ = run_tool(
        db_session, company.id, "create_purchase_order", {"sku": "REORDER-1", "quantity": 40}
    )

    assert result["supplier"] == "Acme Supply"
    assert result["destination"]
    assert result["estimated_total"] == pytest.approx(12.50 * 40)


@pytest.mark.parametrize(
    "quantity,fragment",
    [(0, "positive"), (-5, "positive"), (999_999, "beyond what can be proposed")],
)
def test_an_impossible_quantity_is_refused_correctably(
    quantity, fragment, db_session, company, orderable
):
    result, _ = run_tool(
        db_session,
        company.id,
        "create_purchase_order",
        {"sku": "REORDER-1", "quantity": quantity},
    )

    assert fragment in result["error"]
    assert db_session.query(AssistantAction).count() == 0


def test_an_unknown_sku_comes_back_as_a_correctable_error(db_session, company, orderable):
    result, _ = run_tool(
        db_session, company.id, "create_purchase_order", {"sku": "NOPE", "quantity": 10}
    )

    assert "No product with SKU" in result["error"]
    assert db_session.query(AssistantAction).count() == 0


def test_a_product_with_no_cost_is_refused_at_proposal_time(
    db_session, company, supplier, make_product, make_warehouse
):
    """Caught before it reaches a human's queue, not at the click."""
    product = make_product(company, sku="FREE-1")
    product.unit_cost = 0
    make_warehouse(company)
    db_session.commit()

    result, _ = run_tool(
        db_session, company.id, "create_purchase_order", {"sku": "FREE-1", "quantity": 10}
    )

    assert "no unit cost" in result["error"]


def test_a_proposal_cannot_be_made_against_another_tenants_product(
    db_session, company, other_company, supplier, make_product
):
    theirs = make_product(other_company, sku="THEIRS-PO")
    theirs.unit_cost = 10
    db_session.commit()

    result, _ = run_tool(
        db_session, company.id, "create_purchase_order", {"sku": "THEIRS-PO", "quantity": 5}
    )

    assert "No product with SKU" in result["error"]


@pytest.mark.anyio
async def test_a_model_that_wants_an_order_still_only_gets_a_proposal(
    db_session, company, orderable
):
    runtime = Proposing(quantity=250)
    events = [
        e
        async for e in assistant_service.converse(
            runtime=runtime,
            db=db_session,
            company_id=company.id,
            question="reorder the widget",
        )
    ]

    assert runtime.result["status"] == "proposed"
    assert db_session.query(PurchaseOrder).count() == 0
    assert any(e["type"] == "tool" for e in events)


# ---------------------------------------------------------------------------
# Approval is the only way through
# ---------------------------------------------------------------------------
def test_approving_creates_the_real_purchase_order(db_session, company, orderable, admin_user):
    service = ActionService(db_session)
    action, error = service.propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=100
    )
    assert error is None

    service.approve(company_id=company.id, action_id=action.id, user_id=admin_user.id)
    db_session.commit()

    assert action.status == STATUS_APPROVED
    order = db_session.query(PurchaseOrder).filter_by(id=action.result_id).one()
    assert order.company_id == company.id
    # A draft, exactly as a hand-created one is: approving the suggestion is
    # agreeing it is worth ordering, not agreeing it has been delivered.
    assert order.status == "draft"

    item = db_session.query(POItem).filter_by(po_id=order.id).one()
    assert item.quantity == 100


def test_an_approver_can_amend_the_quantity_and_both_numbers_survive(
    db_session, company, orderable, admin_user
):
    """The interesting case.

    A human who changes 500 to 50 is telling you something about the model. If
    the amendment overwrote the proposal, that signal would be gone -- so the
    two live in separate columns and the audit log carries both.
    """
    service = ActionService(db_session)
    action, _ = service.propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=500
    )

    service.approve(
        company_id=company.id,
        action_id=action.id,
        user_id=admin_user.id,
        overrides={"quantity": 50},
    )
    db_session.commit()

    assert action.proposed_payload["quantity"] == 500
    assert action.executed_payload["quantity"] == 50
    assert action.executed_payload["estimated_total"] == pytest.approx(12.50 * 50)

    item = db_session.query(POItem).filter_by(po_id=action.result_id).one()
    assert item.quantity == 50


def test_rejecting_keeps_the_proposal(db_session, company, orderable, admin_user):
    """Rejections are the most useful rows in the table -- they are the clearest
    evidence the model is wrong about something."""
    service = ActionService(db_session)
    action, _ = service.propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=100
    )

    service.reject(
        company_id=company.id,
        action_id=action.id,
        user_id=admin_user.id,
        reason="We have one on order already.",
    )
    db_session.commit()

    assert action.status == STATUS_REJECTED
    assert action.error == "We have one on order already."
    assert action.executed_payload is None
    assert db_session.query(PurchaseOrder).count() == 0


def test_a_proposal_cannot_be_decided_twice(db_session, company, orderable, admin_user):
    service = ActionService(db_session)
    action, _ = service.propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    service.approve(company_id=company.id, action_id=action.id, user_id=admin_user.id)

    with pytest.raises(OptiStockException) as raised:
        service.approve(company_id=company.id, action_id=action.id, user_id=admin_user.id)

    assert raised.value.code == "ALREADY_DECIDED"


def test_a_stale_proposal_expires_rather_than_executing(
    db_session, company, orderable, admin_user
):
    """A reorder is built on stock levels at a moment. Approving it a week later
    executes a decision made against numbers that no longer exist."""
    service = ActionService(db_session)
    action, _ = service.propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    action.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.flush()

    with pytest.raises(OptiStockException) as raised:
        service.approve(company_id=company.id, action_id=action.id, user_id=admin_user.id)

    assert raised.value.code == "PROPOSAL_EXPIRED"
    assert action.status == STATUS_EXPIRED
    assert db_session.query(PurchaseOrder).count() == 0


def test_another_tenants_proposal_is_not_found_rather_than_forbidden(
    db_session, company, other_company, orderable, admin_user
):
    """Filtered on company_id in the query, never checked afterwards -- the
    difference between a missing row and an authorisation bug."""
    action, _ = ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    db_session.commit()

    with pytest.raises(Exception) as raised:
        ActionService(db_session).approve(
            company_id=other_company.id, action_id=action.id, user_id=admin_user.id
        )

    assert "AssistantAction" in str(raised.value) or "not found" in str(
        raised.value
    ).lower()
    assert action.status == STATUS_PROPOSED


# ---------------------------------------------------------------------------
# The audit trail
# ---------------------------------------------------------------------------
def test_the_audit_log_holds_what_the_model_asked_and_what_ran(
    db_session, company, orderable, admin_user
):
    """Item 12 of the spec, and the row that answers "did the human agree?"."""
    service = ActionService(db_session)
    action, _ = service.propose_purchase_order(
        company_id=company.id,
        sku="REORDER-1",
        quantity=500,
        rationale="Only 3 left.",
        model="gemini-3.6-flash",
    )
    service.approve(
        company_id=company.id,
        action_id=action.id,
        user_id=admin_user.id,
        overrides={"quantity": 50},
    )
    db_session.commit()

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_name == "assistant_actions", AuditLog.action == "APPROVE")
        .one()
    )

    assert entry.user_id == admin_user.id
    assert entry.company_id == company.id
    assert entry.timestamp is not None
    assert entry.old_values["proposed"]["quantity"] == 500
    assert entry.old_values["model"] == "gemini-3.6-flash"
    assert entry.old_values["rationale"] == "Only 3 left."
    assert entry.new_values["executed"]["quantity"] == 50
    assert entry.new_values["status"] == STATUS_APPROVED


def test_a_rejection_is_audited_too(db_session, company, orderable, admin_user):
    service = ActionService(db_session)
    action, _ = service.propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    service.reject(company_id=company.id, action_id=action.id, user_id=admin_user.id)
    db_session.commit()

    entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_name == "assistant_actions", AuditLog.action == "REJECT")
        .one()
    )
    assert entry.new_values["status"] == STATUS_REJECTED


def test_the_proposal_records_who_asked_and_what_they_asked(
    db_session, company, orderable, admin_user
):
    run_tool(
        db_session,
        company.id,
        "create_purchase_order",
        {"sku": "REORDER-1", "quantity": 10},
        {"user_id": admin_user.id, "question": "can you reorder that?", "model": "test-model"},
    )

    action = db_session.query(AssistantAction).one()
    assert action.requested_by_user_id == admin_user.id
    assert action.source_question == "can you reorder that?"
    assert action.proposed_by_model == "test-model"


def test_the_model_cannot_forge_who_requested_it(db_session, company, orderable, admin_user):
    """Context comes from the request. A `_context` in the model's arguments is
    stripped, exactly like a company_id would be."""
    run_tool(
        db_session,
        company.id,
        "create_purchase_order",
        {"sku": "REORDER-1", "quantity": 10, "_context": {"user_id": admin_user.id}},
        None,
    )

    action = db_session.query(AssistantAction).one()
    assert action.requested_by_user_id is None


# ---------------------------------------------------------------------------
# The HTTP surface
# ---------------------------------------------------------------------------
def test_approving_requires_authentication(client, db_session, company, orderable):
    action, _ = ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    db_session.commit()

    response = client.post(f"/api/v1/assistant/actions/{action.id}/approve", json={})
    assert response.status_code == 401


def test_the_approvals_list_is_scoped_to_the_company(
    authenticated_client, db_session, company, other_company, orderable, supplier
):
    ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    db_session.commit()

    body = authenticated_client.get("/api/v1/assistant/actions").json()

    assert len(body["actions"]) == 1
    assert body["actions"][0]["proposed"]["sku"] == "REORDER-1"
    assert body["actions"][0]["status"] == STATUS_PROPOSED


# ---------------------------------------------------------------------------
# Status codes
#
# Every one of these was a 500 before. The router raised domain exceptions the
# global handler had no case for, so "you already approved that" -- which is
# what a double-click produces -- reported a server failure. Found by clicking
# through the real screen rather than by any test, which is why they are here
# now.
# ---------------------------------------------------------------------------
def test_another_tenants_proposal_is_a_404_over_http(
    authenticated_client, db_session, company, other_company, orderable, other_auth_headers
):
    """404 rather than 403, deliberately: a 403 confirms the id exists."""
    action, _ = ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/assistant/actions/{action.id}/approve",
        json={},
        headers=other_auth_headers,
    )

    assert response.status_code == 404


def test_a_missing_proposal_is_a_404(authenticated_client):
    import uuid

    response = authenticated_client.post(
        f"/api/v1/assistant/actions/{uuid.uuid4()}/approve", json={}
    )

    assert response.status_code == 404


def test_approving_twice_is_a_409_not_a_500(
    authenticated_client, db_session, company, orderable
):
    """The double-click case. A user will hit this by accident on day one."""
    action, _ = ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    db_session.commit()

    first = authenticated_client.post(
        f"/api/v1/assistant/actions/{action.id}/approve", json={}
    )
    second = authenticated_client.post(
        f"/api/v1/assistant/actions/{action.id}/approve", json={}
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert "already" in second.json()["detail"].lower()


def test_an_expired_proposal_is_a_409_with_a_useful_message(
    authenticated_client, db_session, company, orderable
):
    action, _ = ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    action.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/assistant/actions/{action.id}/approve", json={}
    )

    assert response.status_code == 409
    assert "out of date" in response.json()["detail"]


def test_rejecting_a_decided_proposal_is_also_a_409(
    authenticated_client, db_session, company, orderable
):
    action, _ = ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    db_session.commit()

    authenticated_client.post(f"/api/v1/assistant/actions/{action.id}/reject", json={})
    again = authenticated_client.post(
        f"/api/v1/assistant/actions/{action.id}/reject", json={}
    )

    assert again.status_code == 409


def test_a_read_only_role_cannot_approve(
    authenticated_client, db_session, company, orderable, analyst_headers
):
    """The same roles as creating a purchase order by hand. An assistant
    suggestion must not be a way around the permission."""
    action, _ = ActionService(db_session).propose_purchase_order(
        company_id=company.id, sku="REORDER-1", quantity=10
    )
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/assistant/actions/{action.id}/approve",
        json={},
        headers=analyst_headers,
    )

    assert response.status_code == 403
    assert action.status == STATUS_PROPOSED
