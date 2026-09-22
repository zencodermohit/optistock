from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ScanCreate(BaseModel):
    """One read from a scanner.

    Deliberately speaks in the reader's vocabulary, not the database's. A
    barcode gun knows a SKU string and the warehouse it is bolted to; it does
    not know product UUIDs, and requiring one would mean shipping a copy of the
    catalogue to every device.
    """

    # Exactly one of these identifies the product, enforced below.
    #
    # A barcode gun bolted to a bench is configured with our SKUs and sends
    # `sku`. A phone camera reads whatever the manufacturer printed and sends
    # `barcode`. Accepting both in one request rather than adding a lookup
    # endpoint keeps a scan a single round trip, which matters because the
    # second call is a second thing that can fail on warehouse wifi -- and it
    # would fail AFTER the client had already decided the scan was good.
    sku: Optional[str] = Field(None, min_length=1, max_length=100)
    barcode: Optional[str] = Field(None, min_length=1, max_length=64)
    warehouse_id: UUID
    direction: Literal["in", "out"]
    quantity: int = Field(1, gt=0, le=10_000)

    # Set by the device, not the server. Two scans of the same tag by the same
    # reader within a second are one physical event, and the device is the only
    # thing that can tell us they were the same press of the trigger.
    scan_reference: Optional[str] = Field(
        None,
        max_length=200,
        description="Device-generated id. Repeating it makes the scan a no-op.",
    )
    device_id: Optional[str] = Field(None, max_length=100)

    @model_validator(mode="after")
    def _one_identifier(self) -> "ScanCreate":
        """Exactly one of sku or barcode, never both and never neither.

        Both is refused rather than resolved by precedence. If a device sends
        a SKU and a barcode that disagree, any rule for picking a winner is a
        guess about which one the operator meant, and the wrong guess moves
        stock on the wrong product silently. Refusing is the only answer that
        cannot be quietly wrong.
        """
        if (self.sku is None) == (self.barcode is None):
            raise ValueError("Send exactly one of sku or barcode.")
        return self


class ScanResponse(BaseModel):
    accepted: bool
    sku: str
    quantity_after: int
    duplicate: bool = False
