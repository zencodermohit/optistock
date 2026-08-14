"""Let some products die, and introduce a few that are genuinely new.

The generated history sells every SKU continuously, forever. That is not what a
catalogue looks like. Real ones have a tail: lines that were superseded, ranges
that were dropped, stock that somebody over-ordered in 2024 and is still sitting
on. Three of the seven product workspaces read zero because of it -- dead, new
and discontinued -- and a workspace that can never have contents is a feature
nobody can see.

So this retires a handful of products and launches a handful of others. It does
NOT invent a "discontinued_at" column or a lifecycle state machine. A product is
dead because its sales stop, which is the only evidence the read model uses and
the only evidence a real business would have. The way to make one dead is to
stop selling it.

    python scripts/retire_products.py --dry-run
    python scripts/retire_products.py

Run app.workers.rebuild_projections afterwards. Removing sales rows makes the
daily metrics projection an opinion about a table that no longer says what it
said, and the whole point of that projection being derived is that it can be
re-formed.
"""

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: F401,E402  — completes the ORM registry
from app.core.database import SessionLocal  # noqa: E402

#: How many products stop selling. Small: the tail of a two-hundred line
#: catalogue is a tail, not a third of the range. Eight is enough for the dead
#: workspace to have a shape -- a range of silences, a range of capital -- while
#: leaving the trading figures where they were.
RETIRE_COUNT = 8

#: Of those, how many are also flagged discontinued. Not all of them: a product
#: can stop selling without anybody getting round to marking it, and that gap
#: between "no longer sells" and "no longer listed" is exactly what the dead
#: stock workspace exists to surface.
DISCONTINUE_COUNT = 3

#: How long ago each retired product went quiet, in days. Spread deliberately:
#: a list where everything fell silent on the same day reads as an outage rather
#: than a tail, and the "last sold" column would have nothing to sort by.
QUIET_DAYS = [72, 96, 130, 180, 240, 310, 400, 520]

#: Products launched recently enough to count as new. They need real sales --
#: a new product with stock and no sales classifies as dead, which is true by
#: the letter of the rule and wrong by the spirit of it.
LAUNCHES = [
    ("ELEC-TAB-301-A", "Lenovo Tab M11 128GB", "Electronics", 14500, 21900),
    ("NETW-SWI-302-A", "Netgear 24-Port Gigabit Switch", "Networking", 9800, 15400),
    ("FURN-ERG-303-A", "Green Soul Ergonomic Chair", "Furniture", 8200, 14900),
    ("SAFE-HEL-304-A", "3M Ratchet Hard Hat", "Safety & PPE", 420, 890),
]

#: Sales are only generated for a launch after this many days, so the product
#: has a plausible gap between being received and first being sold.
LAUNCH_AGE_DAYS = 24
LAUNCH_LEAD_DAYS = 4

SEED = 20260814


def retire(session: Session, company_id, company_name: str, dry_run: bool) -> dict:
    rng = random.Random(f"{SEED}-{company_id}")
    now = datetime.now(timezone.utc)

    # The guard measures the OUTCOME, not the action.
    #
    # An earlier script in this project checked for its own side effect in a way
    # that could never be true, ran three times, and produced seven years of
    # seams. So this asks the question the read model asks: does any product
    # already hold stock it has not sold in months? If yes, this has run.
    already = session.execute(
        text(
            """
            SELECT COUNT(*)
            FROM products p
            JOIN inventory i ON i.product_id = p.id
            JOIN warehouses w ON w.id = i.warehouse_id AND w.company_id = p.company_id
            WHERE p.company_id = :cid
              AND i.quantity > 0
              AND COALESCE((
                    SELECT MAX(s.created_at)
                    FROM sale_items si
                    JOIN sales s ON s.id = si.sale_id
                    WHERE si.product_id = p.id
                  ), TIMESTAMPTZ '1970-01-01') < NOW() - INTERVAL '60 days'
            """
        ),
        {"cid": company_id},
    ).scalar()
    if already:
        return {"skipped": f"{already} products are already dead"}

    # Candidates are the WEAKEST sellers of the last year. Retiring a top line
    # would be a bigger lie than the uniform catalogue it is fixing, and it
    # would visibly dent the revenue trend on every other screen.
    candidates = session.execute(
        text(
            """
            SELECT p.id, p.sku, p.name, p.category, p.unit_cost,
                   COALESCE(SUM(si.quantity * si.unit_price), 0) AS revenue
            FROM products p
            LEFT JOIN sale_items si ON si.product_id = p.id
            LEFT JOIN sales s
                   ON s.id = si.sale_id
                  AND s.created_at >= NOW() - INTERVAL '365 days'
            WHERE p.company_id = :cid AND p.status = 'active'
            GROUP BY p.id, p.sku, p.name, p.category, p.unit_cost
            ORDER BY revenue ASC
            LIMIT :n
            """
        ),
        {"cid": company_id, "n": RETIRE_COUNT * 5},
    ).all()

    # Two superseded lines first.
    #
    # Ranking by weakest revenue alone produces eight cheap consumables, because
    # in this catalogue the weakest sellers ARE the cheapest items -- and a dead
    # workspace reporting two lakh against five crore of inventory reads as a
    # rounding error rather than a problem worth a screen.
    #
    # So these two are drawn on a different rule: the weakest sellers among
    # the expensive quarter of the catalogue.
    #
    # There is no product here that is both costly and idle -- the generator
    # gave every SKU demand roughly proportional to its price -- so a
    # superseded line has to be one that WAS selling. Which is what
    # supersession is: a model gets replaced, its sales stop, and the
    # remaining stock sits at full cost. It pairs with the launches below,
    # and the two of them together are the only story in this file.
    #
    # They take the two shortest silences, so only recent months are removed
    # and the four-year revenue history stays intact.
    superseded = session.execute(
        text(
            """
            WITH ranked AS (
                SELECT p.id, p.sku, p.name, p.category, p.unit_cost,
                       COALESCE(SUM(si.quantity * si.unit_price), 0) AS revenue,
                       PERCENT_RANK() OVER (ORDER BY p.unit_cost) AS cost_rank,
                       PERCENT_RANK() OVER (
                           ORDER BY COALESCE(SUM(si.quantity * si.unit_price), 0)
                       ) AS revenue_rank
                FROM products p
                LEFT JOIN sale_items si ON si.product_id = p.id
                LEFT JOIN sales s
                       ON s.id = si.sale_id
                      AND s.created_at >= NOW() - INTERVAL '365 days'
                WHERE p.company_id = :cid AND p.status = 'active'
                GROUP BY p.id, p.sku, p.name, p.category, p.unit_cost
            )
            SELECT id, sku, name, category, unit_cost, revenue
            FROM ranked
            WHERE cost_rank >= 0.75
            ORDER BY revenue ASC
            LIMIT 2
            """
        ),
        {"cid": company_id},
    ).all()

    chosen, used, names = [], set(), set()
    for row in superseded:
        chosen.append(row)
        used.add(row.category)
        names.add(row.name)

    # Then one per remaining category, so the list is not eight variations of
    # the same shelf.
    for row in candidates:
        if len(chosen) >= RETIRE_COUNT:
            break
        if row.category not in used and row.name not in names:
            chosen.append(row)
            used.add(row.category)
            names.add(row.name)
    for row in candidates:
        if len(chosen) >= RETIRE_COUNT:
            break
        # Names, not ids. The seed carries the same product name under two
        # SKUs, and a dead list showing it twice reads as a duplicate row
        # rather than as two lines that were genuinely both dropped.
        if row.id not in {c.id for c in chosen} and row.name not in names:
            chosen.append(row)
            names.add(row.name)

    retired = []
    for row, quiet_days in zip(chosen, QUIET_DAYS):
        cutoff = now - timedelta(days=quiet_days)

        lines = session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE si.product_id = :pid AND s.created_at >= :cutoff
                """
            ),
            {"pid": row.id, "cutoff": cutoff},
        ).scalar()

        if not dry_run:
            session.execute(
                text(
                    """
                    DELETE FROM sale_items si
                    USING sales s
                    WHERE si.sale_id = s.id
                      AND si.product_id = :pid
                      AND s.created_at >= :cutoff
                    """
                ),
                {"pid": row.id, "cutoff": cutoff},
            )

        # What is left on the shelf when a line stops moving.
        #
        # Current stock is no guide: these products were being restocked right
        # up until this script silenced them, and their inventory rows reflect
        # a live SKU. A dropped line is left holding roughly the stock it had
        # on hand when demand stopped -- a few weeks of its old rate -- which
        # is both the realistic figure and the one that makes "capital tied up"
        # mean something. Eight units of binder clips is not capital.
        rate = session.execute(
            text(
                """
                SELECT COALESCE(SUM(si.quantity), 0) / 365.0
                FROM sale_items si
                JOIN sales s ON s.id = si.sale_id
                WHERE si.product_id = :pid
                  AND s.created_at >= :cutoff - INTERVAL '365 days'
                  AND s.created_at < :cutoff
                """
            ),
            {"pid": row.id, "cutoff": cutoff},
        ).scalar()

        held = max(int(float(rate or 0) * rng.randint(30, 75)), rng.randint(15, 60))

        if not dry_run:
            warehouse = session.execute(
                text(
                    """
                    SELECT w.id
                    FROM warehouses w
                    LEFT JOIN inventory i
                           ON i.warehouse_id = w.id AND i.product_id = :pid
                    WHERE w.company_id = :cid AND w.is_active
                    ORDER BY COALESCE(i.quantity, -1) DESC, w.capacity_units DESC
                    LIMIT 1
                    """
                ),
                {"cid": company_id, "pid": row.id},
            ).scalar()
            # Consolidated onto one site by ZEROING the others, not by deleting
            # them. Inventory rows carry movement history, and the database is
            # right to refuse the delete -- a stock record is an audit trail,
            # and the way a real system empties a shelf is an adjustment to
            # zero, not the removal of the evidence that anything was there.
            session.execute(
                text(
                    """
                    UPDATE inventory i
                    SET quantity = 0, reorder_point = 0
                    FROM warehouses w
                    WHERE i.warehouse_id = w.id
                      AND i.product_id = :pid AND w.company_id = :cid
                    """
                ),
                {"pid": row.id, "cid": company_id},
            )
            updated = session.execute(
                text(
                    """
                    UPDATE inventory
                    SET quantity = :qty, last_counted_at = :counted
                    WHERE product_id = :pid AND warehouse_id = :wid
                    """
                ),
                {
                    "pid": row.id,
                    "wid": warehouse,
                    "qty": held,
                    "counted": cutoff,
                },
            ).rowcount

            if not updated:
                # The product had no line at this site at all.
                session.execute(
                    text(
                        """
                        INSERT INTO inventory (id, product_id, warehouse_id,
                                               quantity, reorder_point,
                                               last_counted_at)
                        VALUES (gen_random_uuid(), :pid, :wid, :qty, 0, :counted)
                        """
                    ),
                    {
                        "pid": row.id,
                        "wid": warehouse,
                        "qty": held,
                        "counted": cutoff,
                    },
                )

        retired.append(
            {
                "sku": row.sku,
                "name": row.name,
                "category": row.category,
                "silent_days": quiet_days,
                "lines_removed": lines,
                "held": held,
            }
        )

    # Some of them get formally dropped from the range.
    if not dry_run and retired:
        session.execute(
            text(
                "UPDATE products SET status = 'discontinued' "
                "WHERE sku = ANY(:skus) AND company_id = :cid"
            ),
            {
                "skus": [r["sku"] for r in retired[:DISCONTINUE_COUNT]],
                "cid": company_id,
            },
        )

    # Sales left holding nothing. A sale with no lines is not a sale, and it
    # would drag the average order value down for reasons no report could name.
    emptied = 0
    if not dry_run:
        emptied = session.execute(
            text(
                """
                DELETE FROM sales s
                WHERE s.company_id = :cid
                  AND NOT EXISTS (SELECT 1 FROM sale_items si WHERE si.sale_id = s.id)
                """
            ),
            {"cid": company_id},
        ).rowcount

        # Every surviving sale that lost a line is now claiming a total it no
        # longer contains.
        session.execute(
            text(
                """
                UPDATE sales s
                SET total_amount = totals.amount
                FROM (
                    SELECT si.sale_id, SUM(si.quantity * si.unit_price) AS amount
                    FROM sale_items si
                    JOIN sales s2 ON s2.id = si.sale_id
                    WHERE s2.company_id = :cid
                    GROUP BY si.sale_id
                ) totals
                WHERE s.id = totals.sale_id AND s.total_amount <> totals.amount
                """
            ),
            {"cid": company_id},
        )

    launched = _launch(session, company_id, rng, now, dry_run)

    if not dry_run:
        session.commit()

    return {
        "company": company_name,
        "retired": retired,
        "discontinued": [r["sku"] for r in retired[:DISCONTINUE_COUNT]],
        "sales_emptied": emptied,
        "launched": launched,
    }


def _launch(session: Session, company_id, rng, now, dry_run: bool) -> list:
    """Add products that are genuinely new, with a short trading history.

    New has to mean new. Backdating a product's created_at and giving it four
    years of sales makes it old with a recent label, which is the opposite of
    the thing being demonstrated.
    """
    warehouses = [
        r[0]
        for r in session.execute(
            text(
                "SELECT id FROM warehouses WHERE company_id = :cid AND is_active"
            ),
            {"cid": company_id},
        ).all()
    ]
    customers = [
        r[0]
        for r in session.execute(
            text("SELECT id FROM customers WHERE company_id = :cid LIMIT 50"),
            {"cid": company_id},
        ).all()
    ]
    if not warehouses or not customers:
        return []

    # The tenant's own SKU convention, read from what it already has rather
    # than assumed. TechNova's lines end -A and GreenLeaf's end -B.
    suffix = session.execute(
        text(
            "SELECT RIGHT(sku, 1) FROM products WHERE company_id = :cid "
            "GROUP BY RIGHT(sku, 1) ORDER BY COUNT(*) DESC LIMIT 1"
        ),
        {"cid": company_id},
    ).scalar() or "A"

    launched = []
    for template, name, category, cost, price in LAUNCHES:
        sku = template[:-1] + suffix
        exists = session.execute(
            text("SELECT 1 FROM products WHERE sku = :sku AND company_id = :cid"),
            {"sku": sku, "cid": company_id},
        ).scalar()
        if exists:
            continue

        created = now - timedelta(days=LAUNCH_AGE_DAYS)
        if dry_run:
            launched.append({"sku": sku, "name": name, "sales": "—", "stock": "—"})
            continue

        product_id = session.execute(
            text(
                """
                INSERT INTO products (id, company_id, sku, name, category,
                                      unit_cost, selling_price, status,
                                      created_at, updated_at)
                VALUES (gen_random_uuid(), :cid, :sku, :name, :cat,
                        :cost, :price, 'active', :created, :created)
                RETURNING id
                """
            ),
            {
                "cid": company_id,
                "sku": sku,
                "name": name,
                "cat": category,
                "cost": cost,
                "price": price,
                "created": created,
            },
        ).scalar()

        stocked = rng.sample(warehouses, k=min(2, len(warehouses)))

        # A launch curve rather than a flat line: slow at first, building as the
        # range gets picked up. Flat sales from day one is the one shape a new
        # product never has.
        sold = 0
        for day in range(LAUNCH_LEAD_DAYS, LAUNCH_AGE_DAYS):
            age = (day - LAUNCH_LEAD_DAYS) / (LAUNCH_AGE_DAYS - LAUNCH_LEAD_DAYS)
            if rng.random() > 0.25 + 0.55 * age:
                continue
            when = now - timedelta(
                days=LAUNCH_AGE_DAYS - day, hours=rng.randint(9, 19)
            )
            quantity = rng.randint(1, 3 + int(4 * age))
            sale_id = session.execute(
                text(
                    """
                    INSERT INTO sales (id, company_id, customer_id,
                                       source_warehouse_id, status, total_amount,
                                       created_at)
                    VALUES (gen_random_uuid(), :cid, :cust, :wid, 'completed',
                            :total, :at)
                    RETURNING id
                    """
                ),
                {
                    "cid": company_id,
                    "cust": rng.choice(customers),
                    "wid": rng.choice(stocked),
                    "total": quantity * price,
                    "at": when,
                },
            ).scalar()
            session.execute(
                text(
                    """
                    INSERT INTO sale_items (id, sale_id, product_id, quantity,
                                            unit_price)
                    VALUES (gen_random_uuid(), :sid, :pid, :qty, :price)
                    """
                ),
                {"sid": sale_id, "pid": product_id, "qty": quantity, "price": price},
            )
            sold += quantity

        # Stock sized from the demand the launch actually saw.
        #
        # Written after the sales rather than before, because a launch has no
        # rate until it has sold something. Allocating a warehouse-sized
        # holding up front gave the new products years of cover and put them
        # straight to the top of the OVERSTOCKED workspace -- correct
        # arithmetic on a nonsense input, and the opposite of the thing a new
        # product is supposed to demonstrate.
        rate = sold / max(LAUNCH_AGE_DAYS - LAUNCH_LEAD_DAYS, 1)
        target = max(int(rate * rng.randint(45, 75)), 20)
        for i, warehouse in enumerate(stocked):
            # Split unevenly. Two sites holding identical counts is the shape
            # of generated data, not of a distribution.
            share = 0.62 if i == 0 else 0.38
            quantity = max(int(target * share), 8)
            session.execute(
                text(
                    """
                    INSERT INTO inventory (id, product_id, warehouse_id, quantity,
                                           reorder_point, last_counted_at)
                    VALUES (gen_random_uuid(), :pid, :wid, :qty, :rp, NOW())
                    """
                ),
                {
                    "pid": product_id,
                    "wid": warehouse,
                    "qty": quantity,
                    "rp": max(int(rate * 14), 5),
                },
            )

        launched.append({"sku": sku, "name": name, "sales": sold, "stock": target})

    return launched


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        companies = session.execute(text("SELECT id, name FROM companies")).all()
        for company_id, name in companies:
            result = retire(session, company_id, name, args.dry_run)
            print(f"\n=== {name} ===")
            if "skipped" in result:
                print(f"  skipped: {result['skipped']}")
                continue
            for row in result["retired"]:
                flag = " [discontinued]" if row["sku"] in result["discontinued"] else ""
                print(
                    f"  retired  {row['sku']:20} {row['name'][:34]:34} "
                    f"silent {row['silent_days']:>3}d  "
                    f"removed {row['lines_removed']:>4} lines  "
                    f"holds {row['held']:>4}{flag}"
                )
            for row in result["launched"]:
                print(
                    f"  launched {row['sku']:20} {row['name'][:34]:34} "
                    f"{row['sales']} units sold, {row['stock']} stocked"
                )
            print(f"  empty sales removed: {result['sales_emptied']}")
        if args.dry_run:
            print("\nDry run — nothing was written.")
        else:
            print(
                "\nNow rebuild the projection:\n"
                "  python -m app.workers.rebuild_projections"
            )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
