"""Zones — the physical areas inside a warehouse.

A warehouse is not a bucket. Stock sits somewhere, and "somewhere" is what a
floor manager actually navigates by: the electronics aisles are full, the
packaging corner is empty, and nobody thinks about it as one number.

A zone here is defined by WHAT IT HOLDS rather than by an arbitrary letter. Zone
membership is derived from the product's category rather than stored per stock
line, which is why there is no zone_id on `inventory`:

*   It matches how these buildings are really organised. Furniture goes with
    furniture because of what it is, not because someone assigned it a slot.
*   Membership can never drift out of sync with the catalogue. Recategorise a
    product and it moves zone in the same instant, with no backfill and no
    second source of truth to reconcile.
*   It costs one join instead of a column on 315 rows and a migration every
    time the layout changes.

The trade is that a zone cannot hold two categories, and one product cannot be
split across two zones. Both are true of this dataset and neither is worth a
join table until they stop being true.

Capacity IS stored, because it is a property of the building rather than of the
stock -- a mezzanine holds what it holds regardless of what is on it today, and
it is the denominator that makes utilisation a measurement rather than a count.
"""

import uuid

from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.database import Base


class WarehouseZone(Base):
    __tablename__ = "warehouse_zones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Carried on the row rather than reached through the warehouse, for the
    # same reason every other table here does it: one filter, no join, and no
    # way for a query to forget the tenant.
    company_id = Column(
        UUID(as_uuid=True), ForeignKey("companies.id"), index=True, nullable=False
    )
    warehouse_id = Column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), index=True, nullable=False
    )

    #: The letter on the floor. A, B, C -- what people say out loud.
    code = Column(String(4), nullable=False)
    #: What it holds. Shown beside the code, because "Zone B" tells a new
    #: starter nothing and "Zone B - Furniture" tells them everything.
    name = Column(String(80), nullable=False)
    #: Matches Product.category. This is the join that decides membership.
    category = Column(String(80), nullable=False)

    capacity_units = Column(Integer, nullable=False, default=0)

    __table_args__ = (
        # One zone per category per warehouse. Two zones claiming the same
        # category would make every stock line count twice, and utilisation
        # would quietly exceed 100% for reasons nobody could find.
        UniqueConstraint(
            "warehouse_id", "category", name="uq_warehouse_zone_category"
        ),
        UniqueConstraint("warehouse_id", "code", name="uq_warehouse_zone_code"),
    )
