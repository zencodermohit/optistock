"""Restore the relative sizes of the warehouses

The previous migration rescaled capacity from what each building held, using a
single target utilisation. That fixed the original defect -- capacities of
50,000 against stock in the low thousands -- and introduced a worse one: with
every site solved for the same target, every site landed on exactly 76%.

Which made the utilisation donut on the network page useless. Four identical
numbers cannot tell you which building is under pressure, and "which building is
under pressure" is the only question that page exists to answer. It also
flattened the buildings on the 3D landing screen, since their footprints come
from capacity.

The mistake was deriving capacity per building from that building's own
contents. Capacity is a property of the STRUCTURE -- a mezzanine holds what it
holds whatever is on it today -- so it must not be a function of what happens to
be inside.

This restores the relative sizes the seed originally expressed (Mumbai is the
big hub, Bangalore is the small one) and scales the whole set so the NETWORK
averages a realistic figure. Utilisation is then free to differ per site,
because it is stock divided by a size that no longer moves to meet it.

Revision ID: c4f8a2b61e73
Revises: b7d3e1f95a24
Create Date: 2026-08-14

"""

import sqlalchemy as sa
from alembic import op

revision = "c4f8a2b61e73"
down_revision = "b7d3e1f95a24"
branch_labels = None
depends_on = None

#: Relative floor area by site, keyed on the location code the seed assigns.
#: Reference data: a business configures this once and it does not change with
#: the stock. Anything unrecognised gets the median weight rather than being
#: skipped, so a warehouse added later is merely average rather than invisible.
SITE_WEIGHT = {
    "MUM": 50,  # the main hub
    "CHN": 40,  # port facility
    "DEL": 35,  # distribution centre
    "PUN": 30,
    "BLR": 25,  # the smallest site
}
DEFAULT_WEIGHT = 35

#: What the NETWORK averages. Individual sites land wherever their own stock
#: puts them against a size that is fixed independently -- which is the whole
#: point, and what makes one site reading 95% while another reads 48% a fact
#: rather than an artefact.
NETWORK_TARGET = 0.76


def _weight(location_code: str | None) -> int:
    if not location_code:
        return DEFAULT_WEIGHT
    for prefix, weight in SITE_WEIGHT.items():
        if prefix in location_code.upper():
            return weight
    return DEFAULT_WEIGHT


def upgrade() -> None:
    conn = op.get_bind()

    companies = conn.execute(
        sa.text("SELECT DISTINCT company_id FROM warehouses")
    ).fetchall()

    for (company_id,) in companies:
        rows = conn.execute(
            sa.text(
                """
                SELECT w.id, w.location_code,
                       COALESCE(SUM(i.quantity), 0) AS held
                FROM warehouses w
                LEFT JOIN inventory i ON i.warehouse_id = w.id
                WHERE w.company_id = :cid
                GROUP BY w.id, w.location_code
                """
            ),
            {"cid": company_id},
        ).fetchall()
        if not rows:
            continue

        total_held = sum(int(r.held) for r in rows)
        weights = {r.id: _weight(r.location_code) for r in rows}
        total_weight = sum(weights.values()) or 1

        # One pot of capacity for the network, shared out by floor area.
        network_capacity = (
            max(int(total_held / NETWORK_TARGET), len(rows))
            if total_held > 0
            else 1000 * len(rows)
        )

        for row in rows:
            capacity = max(int(network_capacity * weights[row.id] / total_weight), 1)
            conn.execute(
                sa.text("UPDATE warehouses SET capacity_units = :c WHERE id = :wid"),
                {"c": capacity, "wid": row.id},
            )

            # Zones share their building out the same way as before: half by
            # what they actually store, half evenly. Recomputed here because
            # their parent's capacity just moved underneath them.
            held_by_category = dict(
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
                    {"wid": row.id},
                ).fetchall()
            )
            site_held = sum(int(v) for v in held_by_category.values())
            zones = conn.execute(
                sa.text(
                    "SELECT id, category FROM warehouse_zones WHERE warehouse_id = :wid"
                ),
                {"wid": row.id},
            ).fetchall()
            if not zones:
                continue

            equal_share = capacity / len(zones)
            for zone in zones:
                units = int(held_by_category.get(zone.category, 0))
                proportional = (
                    (units / site_held * capacity) if site_held > 0 else equal_share
                )
                allowance = 0.55 * proportional + 0.45 * equal_share
                conn.execute(
                    sa.text(
                        "UPDATE warehouse_zones SET capacity_units = :c WHERE id = :zid"
                    ),
                    {"c": max(int(allowance), 1), "zid": zone.id},
                )


def downgrade() -> None:
    # Nothing to restore. The previous values were the flattened ones this
    # migration exists to correct, and putting them back would reintroduce the
    # defect.
    pass
