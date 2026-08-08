from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import RequireRole
from app.core.exceptions import OptiStockException
from app.modules.events import types as event_types
from app.modules.events.publisher import record_event
from app.modules.ingest.schemas import ScanCreate, ScanResponse
from app.modules.inventory.models import InventoryMovement
from app.modules.inventory.service import InventoryService
from app.modules.products.models import Product

router = APIRouter(prefix="/api/v1/ingest", tags=["Ingest"])


@router.post("/scan", response_model=ScanResponse)
def record_scan(
    scan: ScanCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(RequireRole(["admin", "manager", "staff"])),
):
    """Accept one read from a scanner and move stock by it.

    This is the seam the hardware plugs into. A barcode gun, an RFID gateway or
    an ESP32 with a scanner module all speak the same three facts -- what, where,
    which way -- and everything downstream (the ledger, the outbox, the alerts,
    the live stream) already exists and does not care that the trigger was
    physical rather than a click. Adding the hardware later becomes a firmware
    exercise, not an architecture change.

    Authenticated like any other client. A device on a warehouse floor is not
    trusted more than a browser: it gets its own account and the narrowest role
    that can move stock.
    """
    product = (
        db.query(Product)
        .filter(
            Product.sku == scan.sku,
            Product.company_id == UUID(current_user["company_id"]),
        )
        .first()
    )
    if not product:
        # 422, not 404: the request was well-formed but names something this
        # tenant does not stock, and a scanner should log that differently from
        # a bad URL.
        raise HTTPException(
            status_code=422, detail=f"No product with SKU '{scan.sku}' in this company."
        )

    # Idempotency. A radio that retries, or a trigger held a beat too long,
    # must not deduct twice. The device's own reference is the key, and
    # replaying it returns the same answer rather than an error -- a retry that
    # 409s is a retry the device has to write special code for.
    if scan.scan_reference:
        reference = _reference(scan)
        already = (
            db.query(InventoryMovement)
            # Matches the partial index in d2b8f5a71c04. The redundant-looking
            # LIKE is what lets the planner use it -- a partial index is only
            # eligible when the query implies its WHERE clause.
            .filter(
                InventoryMovement.reference_id.like("scan:%"),
                InventoryMovement.reference_id == reference,
            )
            .first()
        )
        if already:
            return ScanResponse(
                accepted=True,
                sku=scan.sku,
                quantity_after=already.quantity_after,
                duplicate=True,
            )

    change = scan.quantity if scan.direction == "in" else -scan.quantity
    service = InventoryService(db)

    try:
        inventory = service.adjust_inventory(
            product_id=product.id,
            warehouse_id=scan.warehouse_id,
            company_id=UUID(current_user["company_id"]),
            quantity_change=change,
            movement_type="scan",
            reference_id=_reference(scan),
        )

        # A second event beside the stock.moved the service already staged.
        # They are not the same fact: stock.moved says the number changed,
        # scan.recorded says a device on a floor somewhere saw a physical
        # object. Only one of those survives if the stock movement is later
        # corrected.
        record_event(
            db,
            company_id=UUID(current_user["company_id"]),
            event_type=event_types.SCAN_RECORDED,
            aggregate_type=event_types.AGGREGATE_INVENTORY,
            aggregate_id=inventory.id,
            payload={
                "sku": scan.sku,
                "product_name": product.name,
                "direction": scan.direction,
                "quantity": scan.quantity,
                "device_id": scan.device_id,
            },
        )
        db.commit()
        return ScanResponse(
            accepted=True,
            sku=scan.sku,
            quantity_after=inventory.quantity,
            duplicate=False,
        )
    except OptiStockException as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=e.message)


def _reference(scan: ScanCreate) -> str:
    """Stable ledger reference for a scan, used to write and to de-duplicate.

    The two prefixes are separate namespaces on purpose. Without them a device
    whose id happened to equal another device's scan reference would silently
    de-duplicate against it, and the symptom would be scans that occasionally
    do nothing.
    """
    if scan.scan_reference:
        return f"scan:ref:{scan.scan_reference}"
    return f"scan:dev:{scan.device_id or 'unknown'}"
