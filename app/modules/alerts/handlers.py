"""What the system does when stock crosses a line.

These are the first real consumers. Importing this module is what registers
them, which `app.workers.consumers.main` does explicitly -- a worker that never
imports its handlers starts cleanly, reads the stream and reacts to nothing.

Every handler here is idempotent, because delivery is at-least-once: the relay
can republish and a worker can commit then fail to acknowledge. Idempotency is
not achieved by remembering which events were seen but by the shape of the work
-- raising an alert that already exists is a no-op enforced by a unique index,
and resolving something already resolved matches nothing.
"""

import logging
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.alerts.models import SEVERITY_CRITICAL, SEVERITY_WARNING
from app.modules.alerts.service import (
    TYPE_LOW_STOCK,
    TYPE_OUT_OF_STOCK,
    AlertService,
)
from app.modules.events import types as event_types
from app.workers.consumers import on

logger = logging.getLogger(__name__)


@on(event_types.STOCK_BELOW_REORDER_POINT)
def raise_low_stock_alert(db: Session, event: dict) -> None:
    payload = event.get("payload", {})
    service = AlertService(db)

    alert = service.open_alert(
        company_id=UUID(event["company_id"]),
        alert_type=TYPE_LOW_STOCK,
        severity=SEVERITY_WARNING,
        subject_type="inventory",
        subject_id=UUID(event["aggregate_id"]),
        title=f"{payload.get('product_name', 'A product')} is below its reorder point",
        # The evidence, not a rendered sentence. The UI can phrase it however it
        # likes, and anyone asking "why did this fire?" gets the actual numbers
        # rather than a paraphrase of them.
        detail={
            "sku": payload.get("sku"),
            "product_name": payload.get("product_name"),
            "warehouse_name": payload.get("warehouse_name"),
            "quantity": payload.get("quantity"),
            "reorder_point": payload.get("reorder_point"),
            "reason": "Stock fell to or below the configured reorder point.",
        },
        triggered_by_event_id=UUID(event["event_id"]),
    )
    if alert is None:
        logger.debug("Low-stock alert already open for %s", event["aggregate_id"])


@on(event_types.STOCK_DEPLETED)
def raise_out_of_stock_alert(db: Session, event: dict) -> None:
    payload = event.get("payload", {})
    service = AlertService(db)
    inventory_id = UUID(event["aggregate_id"])
    company_id = UUID(event["company_id"])

    service.open_alert(
        company_id=company_id,
        alert_type=TYPE_OUT_OF_STOCK,
        severity=SEVERITY_CRITICAL,
        subject_type="inventory",
        subject_id=inventory_id,
        title=f"{payload.get('product_name', 'A product')} is out of stock",
        detail={
            "sku": payload.get("sku"),
            "product_name": payload.get("product_name"),
            "warehouse_name": payload.get("warehouse_name"),
            "quantity": 0,
            "reorder_point": payload.get("reorder_point"),
            "reason": "Stock reached zero.",
        },
        triggered_by_event_id=UUID(event["event_id"]),
    )

    # Out of stock supersedes low stock. Leaving both open would show a warning
    # and a critical for one physical fact, and the warning is the less true of
    # the two.
    service.resolve_matching(
        company_id=company_id,
        alert_type=TYPE_LOW_STOCK,
        subject_type="inventory",
        subject_id=inventory_id,
    )


@on(event_types.STOCK_MOVED)
def clear_alerts_when_stock_recovers(db: Session, event: dict) -> None:
    """Close alerts once the stock they complained about has been replenished.

    Without this, alerts only ever accumulate: the list becomes a history of
    everything that was ever low rather than a list of what needs attention, and
    a list nobody can trust to be current is a list nobody reads.

    Driven by `stock.moved` rather than by a threshold crossing because
    recovering is not a crossing anyone emits -- a delivery takes a product from
    5 to 500 in one movement, and the interesting fact is simply that it is now
    comfortably above the line.
    """
    payload = event.get("payload", {})
    quantity = payload.get("quantity_after")
    reorder_point = payload.get("reorder_point") or 0
    if quantity is None:
        return

    company_id = UUID(event["company_id"])
    inventory_id = UUID(event["aggregate_id"])
    service = AlertService(db)

    if quantity > 0:
        service.resolve_matching(
            company_id=company_id,
            alert_type=TYPE_OUT_OF_STOCK,
            subject_type="inventory",
            subject_id=inventory_id,
        )

    if reorder_point > 0 and quantity > reorder_point:
        service.resolve_matching(
            company_id=company_id,
            alert_type=TYPE_LOW_STOCK,
            subject_type="inventory",
            subject_id=inventory_id,
        )
