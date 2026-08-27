"""Give the demo catalogue a visible spread of stock health.

The classification was already varied -- 136 healthy, 50 overstocked, 7
growing, 5 dead, 1 at risk, 1 critical -- but the Product intelligence list is
sorted by REVENUE, and the biggest earners were all healthy. So the first
screen anyone looks at was a column of green badges, and a demo of a system
whose whole purpose is spotting trouble showed no trouble.

This changes stock levels, and nothing else. Not revenue, not sales history,
not costs or prices -- those come from four years of recorded trading and are
what every figure on every screen is computed from. On-hand quantity is the one
input that decides health without touching any of that:

    critical      selling, and nothing on any shelf     on_hand = 0
    at_risk       under two weeks of cover              on_hand = rate x ~9
    overstocked   more than six months of cover         on_hand = rate x ~220
    healthy       comfortably in between                left alone

Changing it is not a cosmetic edit. Stock drives the stockout-risk screen, the
reorder recommendations and the alert consumers, so a product moved to critical
here shows up as critical everywhere, consistently, because every screen reads
the same number. That is the point -- a demo where the badge and the reorder
advice disagree is worse than one with no badges at all.

Applied to the TOP of the revenue ranking on purpose. Trouble on a product
nobody has heard of is a row in a table; trouble on the line that earns the
most is the reason this software exists.

    python -m scripts.shape_demo_stock --plan     # show what would change
    python -m scripts.shape_demo_stock --apply    # write the quantities
"""

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.database import SessionLocal  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("stock")

#: How many of the top earners to place in each state. Deliberately a small
#: minority: a catalogue where a third of the lines are on fire reads as broken
#: data rather than as a business with problems worth noticing.
SHAPE = [
    ("critical", 3),
    ("at_risk", 6),
    ("overstocked", 5),
]

#: Cover targets in days, well clear of the thresholds in
#: app/modules/products/intelligence.py rather than sitting on them -- a value
#: on the boundary flips category when a single unit sells.
#:
#: The rate they multiply is measured over THIRTY days because that is the
#: window the Product intelligence screen opens on. Sized against a 90-day
#: rate, every at-risk product came out healthy: a slower recent month means
#: the same quantity buys more cover, and the badge is computed from the
#: window being viewed, not from the one the quantities were designed for.
COVER = {"at_risk": 7, "overstocked": 260}


def candidates(db):
    """Top earners with a real sales rate, richest first.

    A daily rate above zero is required: the classifier only calls a product
    critical if it is SELLING and empty, so an empty product nobody buys is
    correctly just dead stock and moving it here would achieve nothing.
    """
    # Aggregated separately and then joined. Summing sales and stock in one
    # query fans out -- a product on three shelves counts its whole sales
    # history three times -- and the first version of this reported revenue at
    # triple the real figure and sized every target off the inflated rate.
    rows = db.execute(text("""
            WITH sold AS (
                SELECT si.product_id,
                       SUM(si.quantity * si.unit_price) AS revenue,
                       SUM(si.quantity) FILTER (
                           WHERE s.created_at >= now() - interval '30 days'
                       ) AS recent_units
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                GROUP BY si.product_id
            ),
            held AS (
                SELECT product_id, SUM(quantity) AS on_hand
                FROM inventory GROUP BY product_id
            )
            SELECT p.id::text AS id, p.sku, p.name,
                   COALESCE(sold.revenue, 0)::numeric AS revenue,
                   COALESCE(sold.recent_units, 0)::numeric / 30.0 AS daily_rate,
                   COALESCE(held.on_hand, 0) AS on_hand
            FROM products p
            JOIN companies c ON c.id = p.company_id AND c.name = 'TechNova Industries'
            LEFT JOIN sold ON sold.product_id = p.id
            LEFT JOIN held ON held.product_id = p.id
            WHERE COALESCE(sold.recent_units, 0) > 0
            ORDER BY revenue DESC
            LIMIT 40
            """)).mappings()
    return [dict(r) for r in rows]


def plan(db):
    """Which products move where, and to what quantity."""
    pool = candidates(db)
    moves = []
    index = 0
    for state, count in SHAPE:
        for _ in range(count):
            if index >= len(pool):
                break
            row = pool[index]
            index += 1
            rate = float(row["daily_rate"]) or 0.1
            target = 0 if state == "critical" else int(round(rate * COVER[state]))
            moves.append(
                {
                    **row,
                    "state": state,
                    "from": int(row["on_hand"]),
                    "to": max(target, 0),
                }
            )
    return moves


def apply(db, moves):
    """Write the quantity onto the product's LARGEST stock line.

    One line rather than spread across sites, because the classifier sums a
    product's stock across warehouses -- and concentrating the change keeps the
    per-warehouse figures on the inventory screen looking like real holdings
    instead of every site holding an identical suspicious number.
    """
    for move in moves:
        rows = db.execute(
            text("""
                SELECT id::text AS id FROM inventory
                WHERE product_id = CAST(:pid AS uuid)
                ORDER BY quantity DESC
                """),
            {"pid": move["id"]},
        ).fetchall()
        if not rows:
            log.warning("  %s has no stock line to adjust", move["sku"])
            continue
        # Everything onto the biggest line; the rest go to zero so the total
        # is exactly the target rather than the target plus whatever else sat
        # on other shelves.
        for position, row in enumerate(rows):
            db.execute(
                text("UPDATE inventory SET quantity = :q WHERE id = CAST(:id AS uuid)"),
                {"q": move["to"] if position == 0 else 0, "id": row.id},
            )
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not (args.plan or args.apply):
        parser.error("choose --plan or --apply")

    db = SessionLocal()
    try:
        moves = plan(db)
        log.info(
            "%-14s %-34s %10s %8s -> %6s",
            "STATE",
            "PRODUCT",
            "REVENUE",
            "ON HAND",
            "NEW",
        )
        for m in moves:
            log.info(
                "%-14s %-34s %10s %8d -> %6d",
                m["state"],
                m["name"][:34],
                f"{float(m['revenue']):,.0f}",
                m["from"],
                m["to"],
            )
        if args.apply:
            apply(db, moves)
            log.info("\nApplied. Revenue, sales history and prices untouched.")
        else:
            log.info("\nNothing written. Re-run with --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
