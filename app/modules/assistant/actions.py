"""Proposing, approving and rejecting the assistant's suggested writes.

The whole module is built around one rule: `propose` never changes anything but
the proposals table, and `execute` is only ever reached from `approve`, which
requires a user id. There is no code path from a tool call to a purchase order.
If you are auditing this file, that is the property to check, and it is why
execution lives here rather than in tools.py -- the model's tools cannot import
their way to it.

Approval runs the same PurchaseOrderService that the Purchase Orders screen
runs. An assistant-created order is not a special kind of order; it is an
ordinary one whose paperwork happens to record where the idea came from.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import OptiStockException, ResourceNotFoundError
from app.modules.assistant.models import (
    ACTION_CREATE_PURCHASE_ORDER,
    STATUS_APPROVED,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PROPOSED,
    STATUS_REJECTED,
    AssistantAction,
)
from app.modules.audit.schemas import AuditLogCreate
from app.modules.audit.service import AuditService
from app.modules.inventory.models import Inventory
from app.modules.products.models import Product
from app.modules.purchase_orders.schemas import POItemBase, PurchaseOrderCreate
from app.modules.purchase_orders.service import PurchaseOrderService
from app.modules.suppliers.models import Supplier
from app.modules.warehouses.models import Warehouse

logger = logging.getLogger(__name__)

#: A ceiling on what a single proposal may ask for. Not a safety mechanism --
#: approval is the safety mechanism -- but a proposal for 900,000 units is
#: noise in a queue a human has to read, and cheap to refuse at the door.
MAX_PROPOSED_QUANTITY = 10_000


class ActionService:
    def __init__(self, db: Session):
        self.db = db

    # -- Proposing ----------------------------------------------------------
    def propose_purchase_order(
        self,
        *,
        company_id: UUID,
        sku: str,
        quantity: int,
        rationale: Optional[str] = None,
        source_question: Optional[str] = None,
        model: Optional[str] = None,
        requested_by_user_id: Optional[UUID] = None,
    ) -> Tuple[Optional[AssistantAction], Optional[str]]:
        """Record what the model thinks should be ordered. Change nothing else.

        Returns (action, error). The error is a sentence for the model to read
        and relay, not an exception -- a proposal the model got slightly wrong
        should come back correctable, the way every other tool failure does.

        The references are resolved HERE, from the tenant's own rows, rather
        than taken from the model. The model supplies a SKU and a number; which
        warehouse, which supplier and what the thing costs are looked up under
        the company_id bound by the caller. A model cannot propose an order
        against another company's warehouse because it never names one.
        """
        quantity = int(quantity or 0)
        if quantity <= 0:
            return None, "Quantity must be a positive whole number."
        if quantity > MAX_PROPOSED_QUANTITY:
            return None, (
                f"{quantity:,} units is beyond what can be proposed in one order "
                f"(limit {MAX_PROPOSED_QUANTITY:,}). Propose a smaller quantity, "
                "or tell the user to raise it on the Purchase Orders screen."
            )

        product = (
            self.db.query(Product)
            .filter(Product.company_id == company_id, Product.sku == sku)
            .first()
        )
        if product is None:
            return None, (
                f"No product with SKU '{sku}' exists. Check the SKU with "
                "search_products before proposing an order for it."
            )

        warehouse, warehouse_note = self._destination(company_id, product.id)
        if warehouse is None:
            return None, warehouse_note

        supplier = (
            self.db.query(Supplier)
            .filter(Supplier.company_id == company_id, Supplier.is_active.is_(True))
            .order_by(Supplier.reliability_score.desc().nullslast(), Supplier.name)
            .first()
        )
        if supplier is None:
            return None, (
                "This company has no active supplier on file, so there is "
                "nobody to order from. Add one on the Suppliers screen first."
            )

        unit_cost = float(product.unit_cost or 0)
        if unit_cost <= 0:
            # Caught here rather than at approval. A proposal that cannot
            # possibly execute should never reach a human's queue, and finding
            # out at the click is a worse experience than being told now.
            return None, (
                f"'{product.sku}' has no unit cost recorded, so an order value "
                "cannot be calculated. Set its cost on the Products screen first."
            )

        payload = {
            "sku": product.sku,
            "product_id": str(product.id),
            "product_name": product.name,
            "quantity": quantity,
            "unit_cost": unit_cost,
            "estimated_total": round(unit_cost * quantity, 2),
            "warehouse_id": str(warehouse.id),
            "warehouse_name": warehouse.name,
            "supplier_id": str(supplier.id),
            "supplier_name": supplier.name,
        }

        action = AssistantAction(
            company_id=company_id,
            action_type=ACTION_CREATE_PURCHASE_ORDER,
            status=STATUS_PROPOSED,
            proposed_payload=payload,
            rationale=rationale,
            source_question=source_question,
            proposed_by_model=model,
            requested_by_user_id=requested_by_user_id,
        )
        self.db.add(action)
        self.db.flush()

        logger.info(
            "assistant.action_proposed",
            extra={
                "action_id": str(action.id),
                "action_type": action.action_type,
                "sku": product.sku,
                "quantity": quantity,
            },
        )
        return action, None

    def _destination(
        self, company_id: UUID, product_id: UUID
    ) -> Tuple[Optional[Warehouse], Optional[str]]:
        """Where the stock should land.

        The warehouse already holding the least of this product, because that is
        where a reorder is usually needed. Falls back to any warehouse for a
        product not yet stocked anywhere -- a first order has to go somewhere,
        and the approver can see which one before agreeing.
        """
        # Joined through the warehouse rather than filtered on the row: an
        # inventory line carries no company_id of its own -- it is tenanted by
        # the product and warehouse it points at -- so the join IS the tenancy
        # check, not a convenience.
        lowest = (
            self.db.query(Warehouse)
            .join(Inventory, Inventory.warehouse_id == Warehouse.id)
            .filter(
                Warehouse.company_id == company_id,
                Inventory.product_id == product_id,
            )
            .order_by(Inventory.quantity.asc())
            .first()
        )
        if lowest is not None:
            return lowest, None

        warehouse = (
            self.db.query(Warehouse)
            .filter(Warehouse.company_id == company_id)
            .order_by(Warehouse.name)
            .first()
        )
        if warehouse is None:
            return None, (
                "This company has no warehouses, so there is nowhere for an "
                "order to be delivered."
            )
        return warehouse, None

    # -- Reading ------------------------------------------------------------
    def list_actions(
        self, company_id: UUID, status: Optional[str] = None, limit: int = 50
    ) -> List[AssistantAction]:
        query = self.db.query(AssistantAction).filter(
            AssistantAction.company_id == company_id
        )
        if status:
            query = query.filter(AssistantAction.status == status)
        return query.order_by(AssistantAction.proposed_at.desc()).limit(limit).all()

    def get(self, company_id: UUID, action_id: UUID) -> AssistantAction:
        """Fetched with the tenant in the filter, never checked afterwards.

        A proposal id is a UUID a client supplies. Filtering on company_id makes
        another tenant's id a 404 rather than a leak, which is the difference
        between a missing row and an authorisation bug.
        """
        action = (
            self.db.query(AssistantAction)
            .filter(
                AssistantAction.id == action_id,
                AssistantAction.company_id == company_id,
            )
            .first()
        )
        if action is None:
            raise ResourceNotFoundError("AssistantAction", str(action_id))
        return action

    # -- Deciding -----------------------------------------------------------
    def approve(
        self,
        *,
        company_id: UUID,
        action_id: UUID,
        user_id: UUID,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> AssistantAction:
        """Execute a proposal, on the authority of a named human.

        `user_id` is not optional and has no default. An approval with nobody
        attached is not an approval, and making it a required argument means
        the type checker refuses to let a caller forget.

        `overrides` lets the approver change the quantity before agreeing. That
        is the interesting case: the resulting purchase order is what the HUMAN
        chose, the proposal keeps what the MODEL asked for, and the audit log
        holds both.
        """
        action = self.get(company_id, action_id)
        self._require_actionable(action)

        final = dict(action.proposed_payload)
        if overrides and "quantity" in overrides:
            quantity = int(overrides["quantity"])
            if quantity <= 0 or quantity > MAX_PROPOSED_QUANTITY:
                raise OptiStockException(
                    code="INVALID_QUANTITY",
                    message=(
                        f"Quantity must be between 1 and {MAX_PROPOSED_QUANTITY:,}."
                    ),
                )
            final["quantity"] = quantity
            final["estimated_total"] = round(final["unit_cost"] * quantity, 2)

        action.decided_by_user_id = user_id
        action.decided_at = datetime.now(timezone.utc)
        action.executed_payload = final

        try:
            purchase_order = self._create_purchase_order(company_id, final)
        except Exception as error:
            # Failed is a distinct state from rejected. Somebody clicked yes;
            # collapsing that into "not approved" would lose the fact that the
            # decision was made and the system could not honour it.
            action.status = STATUS_FAILED
            action.error = str(error)[:500]
            self.db.flush()
            logger.exception(
                "assistant.action_failed", extra={"action_id": str(action_id)}
            )
            raise

        action.status = STATUS_APPROVED
        action.result_id = purchase_order.id
        self.db.flush()

        self._audit(action, user_id, "APPROVE")
        logger.info(
            "assistant.action_approved",
            extra={
                "action_id": str(action.id),
                "purchase_order_id": str(purchase_order.id),
                "amended": final != action.proposed_payload,
            },
        )
        return action

    def reject(
        self, *, company_id: UUID, action_id: UUID, user_id: UUID, reason: str = ""
    ) -> AssistantAction:
        """Decline a proposal, and keep it.

        Rejections are the most useful rows in this table. A proposal nobody
        accepted is the clearest signal that the model is wrong about
        something, and deleting it would throw that away.
        """
        action = self.get(company_id, action_id)
        self._require_actionable(action)

        action.status = STATUS_REJECTED
        action.decided_by_user_id = user_id
        action.decided_at = datetime.now(timezone.utc)
        action.error = reason[:500] or None
        self.db.flush()

        self._audit(action, user_id, "REJECT")
        logger.info("assistant.action_rejected", extra={"action_id": str(action.id)})
        return action

    def _require_actionable(self, action: AssistantAction) -> None:
        if action.status != STATUS_PROPOSED:
            raise OptiStockException(
                code="ALREADY_DECIDED",
                message=f"This proposal was already {action.status}.",
            )
        if not action.is_actionable:
            # Marked as it is discovered rather than by a sweeper job. There is
            # no behaviour that depends on expiry happening promptly, and a
            # cron job to maintain a field nobody reads until it is read is a
            # moving part with no purpose.
            action.status = STATUS_EXPIRED
            self.db.flush()
            raise OptiStockException(
                code="PROPOSAL_EXPIRED",
                message=(
                    "This proposal is out of date -- it was based on stock "
                    "levels from more than a day ago. Ask the assistant again "
                    "to get one built on current numbers."
                ),
            )

    def _create_purchase_order(self, company_id: UUID, payload: Dict[str, Any]):
        """The single place a proposal turns into a real record.

        Delegates to the ordinary PurchaseOrderService, so an assistant-created
        order gets the same tenant validation, the same totals arithmetic and
        the same draft status as one a person creates by hand. It starts as a
        draft for the same reason theirs does: approving the suggestion is
        agreeing it is worth ordering, not agreeing to have it delivered.
        """
        return PurchaseOrderService(self.db).create_po(
            PurchaseOrderCreate(
                supplier_id=UUID(payload["supplier_id"]),
                destination_warehouse_id=UUID(payload["warehouse_id"]),
                items=[
                    POItemBase(
                        product_id=UUID(payload["product_id"]),
                        quantity=payload["quantity"],
                        unit_price=payload["unit_cost"],
                    )
                ],
            ),
            company_id,
        )

    def _audit(self, action: AssistantAction, user_id: UUID, verb: str) -> None:
        """The record that answers "did the human agree with the machine?".

        old_values holds what the model proposed and new_values what was
        actually run, so the two are side by side in one row of a table that
        already exists for compliance. A quantity that changed between them is
        an approver correcting the model, and counting those over time is the
        only honest measure of whether the suggestions are any good.
        """
        AuditService.log_action(
            self.db,
            AuditLogCreate(
                user_id=user_id,
                company_id=action.company_id,
                entity_name="assistant_actions",
                entity_id=action.id,
                action=verb,
                old_values={
                    "source": "assistant",
                    "model": action.proposed_by_model,
                    "proposed": action.proposed_payload,
                    "rationale": action.rationale,
                },
                new_values={
                    "status": action.status,
                    "executed": action.executed_payload,
                    "result_id": str(action.result_id) if action.result_id else None,
                },
            ),
        )
