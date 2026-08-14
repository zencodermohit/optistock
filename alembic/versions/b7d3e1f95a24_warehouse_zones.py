"""Warehouse zones, and honest capacities to measure them against

Creates the zones table, provisions a zone per product category in every
existing warehouse, and — the part worth reading — rescales warehouse capacity.

The stated capacities were round numbers picked to sound like warehouses
(50,000, 35,000) while stock was seeded at realistic per-line quantities. The
result was every site sitting at 4–8% utilisation, which is not a business
problem, it is two unrelated numbers that were never reconciled. Any
visualisation built on it — a capacity ring, a zone heatmap — renders as
"empty" everywhere and carries no signal at all.

This rescales capacity IN PLACE from what each building actually holds, so no
seeded history is destroyed. Nothing about the stock changes; only the
denominator it is measured against.

Revision ID: b7d3e1f95a24
Revises: f4a2c8b91d70
Create Date: 2026-08-14

"""

import uuid

import sqlalchemy as sa
from alembic import op

revision = "b7d3e1f95a24"
down_revision = "f4a2c8b91d70"
branch_labels = None
depends_on = None

#: Code, display name, and the Product.category it draws from. Ordered so the
#: letters are stable: A is always Electronics, in every warehouse, forever.
ZONES = [
    ("A", "Electronics", "Electronics"),
    ("B", "Furniture", "Furniture"),
    ("C", "Office Supplies", "Office Supplies"),
    ("D", "Networking", "Networking"),
    ("E", "Safety & PPE", "Safety & PPE"),
    ("F", "Packaging", "Packaging"),
]

#: What a healthy building runs at. Warehouses are not meant to be full — you
#: cannot receive into a full warehouse — so the target leaves headroom.
TARGET_UTILISATION = 0.76

#: How much of a zone's allowance follows what it actually holds, versus an
#: equal split. At 1.0 every zone lands on the same percentage and the heatmap
#: is a flat colour; at 0.0 capacity ignores what a warehouse really stores. The
#: midpoint is what makes a zone holding more than its share read as pressure.
PROPORTIONAL_WEIGHT = 0.55


def upgrade() -> None:
    op.create_table(
        "warehouse_zones",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("warehouse_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=4), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("capacity_units", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("warehouse_id", "category", name="uq_warehouse_zone_category"),
        sa.UniqueConstraint("warehouse_id", "code", name="uq_warehouse_zone_code"),
    )
    op.create_index(
        "ix_warehouse_zones_warehouse_id", "warehouse_zones", ["warehouse_id"]
    )
    op.create_index("ix_warehouse_zones_company_id", "warehouse_zones", ["company_id"])

    conn = op.get_bind()
    warehouses = conn.execute(
        sa.text("SELECT id, company_id, capacity_units FROM warehouses")
    ).fetchall()

    for warehouse in warehouses:
        # What this building actually holds, per category.
        held = dict(
            conn.execute(
                sa.text(
                    """
                    SELECT p.category, COALESCE(SUM(i.quantity), 0)
                    FROM inventory i
                    JOIN products p ON p.id = i.product_id
                    WHERE i.warehouse_id = :wid
                    GROUP BY p.category
                    """
                ),
                {"wid": warehouse.id},
            ).fetchall()
        )
        total_held = sum(int(v) for v in held.values())

        # Rescale the building. A warehouse holding nothing keeps whatever it
        # was given rather than collapsing to zero capacity.
        capacity = (
            max(int(total_held / TARGET_UTILISATION), 1)
            if total_held > 0
            else int(warehouse.capacity_units or 1000)
        )
        conn.execute(
            sa.text("UPDATE warehouses SET capacity_units = :c WHERE id = :wid"),
            {"c": capacity, "wid": warehouse.id},
        )

        equal_share = capacity / len(ZONES)
        for code, name, category in ZONES:
            units = int(held.get(category, 0))
            proportional = (units / total_held * capacity) if total_held > 0 else 0
            allowance = (
                PROPORTIONAL_WEIGHT * proportional
                + (1 - PROPORTIONAL_WEIGHT) * equal_share
            )
            conn.execute(
                sa.text(
                    """
                    INSERT INTO warehouse_zones
                        (id, company_id, warehouse_id, code, name, category,
                         capacity_units)
                    VALUES (:id, :cid, :wid, :code, :name, :cat, :cap)
                    """
                ),
                {
                    "id": str(uuid.uuid4()),
                    "cid": warehouse.company_id,
                    "wid": warehouse.id,
                    "code": code,
                    "name": name,
                    "cat": category,
                    # At least one, so a zone can never divide by zero when its
                    # utilisation is computed.
                    "cap": max(int(allowance), 1),
                },
            )


def downgrade() -> None:
    # Capacities are deliberately NOT restored. The originals were arbitrary
    # round numbers with no relationship to the stock, and putting them back
    # would reintroduce the defect this migration exists to fix.
    op.drop_index("ix_warehouse_zones_company_id", table_name="warehouse_zones")
    op.drop_index("ix_warehouse_zones_warehouse_id", table_name="warehouse_zones")
    op.drop_table("warehouse_zones")
