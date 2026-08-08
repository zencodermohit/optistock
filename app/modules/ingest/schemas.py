from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ScanCreate(BaseModel):
    """One read from a scanner.

    Deliberately speaks in the reader's vocabulary, not the database's. A
    barcode gun knows a SKU string and the warehouse it is bolted to; it does
    not know product UUIDs, and requiring one would mean shipping a copy of the
    catalogue to every device.
    """

    sku: str = Field(..., min_length=1, max_length=100)
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


class ScanResponse(BaseModel):
    accepted: bool
    sku: str
    quantity_after: int
    duplicate: bool = False
