#!/usr/bin/env python
"""Generate realistic demo data for OptiStock.

Why this is a simulation and not a pile of random inserts
---------------------------------------------------------
The obvious way to seed an inventory system is to invent numbers: pick a stock
level, pick some sales, move on. That produces data that falls apart the moment
anything analyses it — stock levels unrelated to sales history, no stockouts, a
flat demand curve, and an ABC classification where every product looks the same.

Instead this walks 365 days forward per (product, warehouse) line. Demand
depletes stock; hitting the reorder point triggers a restock. Stockouts,
restock cadence, current inventory levels and the movement ledger are all
*emergent* — they are consequences of the simulation rather than values someone
typed. That means the forecast has a real signal to find, ABC produces a real
Pareto curve, and the low-stock alerts fire for products that are genuinely low.

Demand model per product per day:

    rate = base(rank) x seasonal(month) x weekday x growth(trend)
    units = Poisson(rate)

`base(rank)` follows a Zipf distribution, which is what real catalogues look
like: a few products carry most of the volume and there is a long, quiet tail.

Usage
-----
    python seed_db.py            # seed (refuses if data already present)
    python seed_db.py --reset    # wipe and re-seed

Respects DATABASE_URL from the environment.
"""

import argparse
import math
import os
import random
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

import numpy as np
from passlib.context import CryptContext
from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import sessionmaker

# The app refuses to import without a signing key; seeding does not need a real one.
os.environ.setdefault("SECRET_KEY", "seed-script-does-not-issue-tokens")

# Importing the registry guarantees every model is loaded, so foreign keys
# resolve even though this script is not started via app.main.
from app.models import (  # noqa: E402
    Company,
    Customer,
    Inventory,
    InventoryMovement,
    POItem,
    Product,
    PurchaseOrder,
    Sale,
    SaleItem,
    Supplier,
    User,
    Warehouse,
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
RNG = random.Random(20260808)
NP_RNG = np.random.default_rng(20260808)

DEMO_PASSWORD = "Demo@12345"
SIM_DAYS = 365
TENANT_B_DAYS = 90


# ===========================================================================
# Catalogue
# ===========================================================================
WAREHOUSES = [
    ("Mumbai Central Hub", "WH-MUM-001", 50000),
    ("Delhi Distribution Center", "WH-DEL-002", 35000),
    ("Bangalore Tech Park", "WH-BLR-003", 25000),
    ("Chennai Port Facility", "WH-CHN-004", 40000),
]

SUPPLIERS = [
    ("Reliance Digital Wholesale", "wholesale@reliancedigital.in", 0.95),
    ("Tata Components Ltd", "supply@tatacomponents.com", 0.98),
    ("Wipro Peripherals", "orders@wiproperipherals.in", 0.88),
    ("Mahindra Logistics Supply", "vendor@mahindralogistics.com", 0.92),
    ("Godrej Interio B2B", "b2b@godrejinterio.com", 0.97),
    ("D-Link India Partners", "partners@dlink.co.in", 0.85),
    ("Karam Safety Distributors", "sales@karamsafety.in", 0.90),
    ("PackRight Industries", "orders@packright.in", 0.82),
]

CUSTOMERS = [
    ("Infosys Technologies", "procurement@infosys.com"),
    ("Wipro Limited", "supplies@wipro.com"),
    ("HCL Technologies", "orders@hcltech.com"),
    ("Tech Mahindra", "buying@techmahindra.com"),
    ("L&T InfoTech", "purchase@ltimindtree.com"),
    ("Bajaj Finance Ltd", "admin@bajajfinance.in"),
    ("HDFC Bank Operations", "facilities@hdfcbank.com"),
    ("Flipkart Pvt Ltd", "warehouse@flipkart.com"),
    ("Zomato Corporate", "office@zomato.com"),
    ("PhonePe India", "infra@phonepe.com"),
]

# The 30 hand-written "hero" products keep the catalogue believable; the rest
# are generated as variants below so the Pareto curve has enough points.
HERO_PRODUCTS = [
    ("ELEC-LAP-001", 'ProBook Laptop 15" i7', "Electronics", 45000, 72999),
    ("ELEC-MON-002", 'UltraView 27" 4K Monitor', "Electronics", 18000, 28999),
    ("ELEC-TAB-003", 'SmartTab Pro 11" Tablet', "Electronics", 22000, 34999),
    ("ELEC-PHN-004", "NovaPix 5G Smartphone", "Electronics", 15000, 24999),
    ("ELEC-EAR-005", "SoundWave ANC Earbuds", "Electronics", 2500, 4999),
    ("ELEC-CHR-006", "RapidCharge 65W Adapter", "Electronics", 800, 1499),
    ("OFFC-PPR-001", "Premium A4 Paper (500 sheets)", "Office Supplies", 180, 349),
    ("OFFC-PEN-002", "Executive Ballpoint Pen Set", "Office Supplies", 250, 599),
    ("OFFC-BND-003", "Leather Document Binder", "Office Supplies", 400, 899),
    ("OFFC-DSK-004", "Ergonomic Desk Organizer", "Office Supplies", 650, 1299),
    ("OFFC-WHB-005", "Magnetic Whiteboard 4x3ft", "Office Supplies", 1200, 2499),
    ("FURN-CHR-001", "ErgoMax Office Chair", "Furniture", 8500, 14999),
    ("FURN-DSK-002", 'Standing Desk Pro 60"', "Furniture", 12000, 21999),
    ("FURN-CAB-003", "Steel Filing Cabinet 4-Drawer", "Furniture", 5500, 9999),
    ("FURN-SHL-004", "Modular Bookshelf Unit", "Furniture", 3200, 5999),
    ("FURN-TBL-005", "Conference Table 8-Seater", "Furniture", 18000, 32999),
    ("NETW-RTR-001", "Enterprise WiFi 6 Router", "Networking", 4500, 7999),
    ("NETW-SWT-002", "48-Port Managed Switch", "Networking", 12000, 19999),
    ("NETW-CBL-003", "Cat6 Ethernet Cable (100m)", "Networking", 1800, 3499),
    ("NETW-AP-004", "Ceiling Mount Access Point", "Networking", 6000, 10999),
    ("NETW-FWL-005", "Next-Gen Firewall Appliance", "Networking", 35000, 59999),
    ("SAFE-HLM-001", "Industrial Safety Helmet", "Safety & PPE", 350, 699),
    ("SAFE-GLV-002", "Cut-Resistant Work Gloves", "Safety & PPE", 180, 399),
    ("SAFE-VST-003", "Hi-Vis Reflective Vest", "Safety & PPE", 220, 499),
    ("SAFE-KIT-004", "First Aid Kit Industrial", "Safety & PPE", 900, 1799),
    ("PACK-BOX-001", "Corrugated Box (Pack of 50)", "Packaging", 600, 1199),
    ("PACK-TPE-002", "Heavy-Duty Packing Tape (12 rolls)", "Packaging", 350, 699),
    ("PACK-WRP-003", "Bubble Wrap Roll 100m", "Packaging", 450, 899),
    ("PACK-PLT-004", "Wooden Pallet (Standard)", "Packaging", 800, 1499),
    ("PACK-STR-005", "Stretch Film Roll 500mm", "Packaging", 280, 549),
]

# Used to generate the long tail. Real catalogues are mostly variants.
VARIANT_TEMPLATES = {
    "Electronics": (
        ["Logitech", "HP", "Dell", "Lenovo", "Asus", "Acer", "Samsung", "Sony"],
        [
            "Wireless Mouse",
            "Mechanical Keyboard",
            "USB-C Dock",
            "Webcam 1080p",
            "Portable SSD 1TB",
            "Laptop Sleeve",
            "HDMI Cable 2m",
            "Bluetooth Speaker",
        ],
        (600, 9000),
    ),
    "Office Supplies": (
        ["Camlin", "Faber-Castell", "Classmate", "Navneet", "3M", "Kokuyo"],
        [
            "Sticky Notes Pack",
            "Highlighter Set",
            "Stapler Heavy Duty",
            "File Folder Box",
            "Notebook Ruled A5",
            "Correction Tape",
            "Desk Calendar",
            "Binder Clips 100pc",
        ],
        (80, 1200),
    ),
    "Furniture": (
        ["Godrej", "Nilkamal", "Featherlite", "Durian", "Wakefit"],
        [
            "Visitor Chair",
            "Storage Cabinet",
            "Workstation Desk",
            "Mobile Pedestal",
            "Meeting Stool",
            "Partition Panel",
        ],
        (2500, 22000),
    ),
    "Networking": (
        ["D-Link", "TP-Link", "Cisco", "Netgear", "Ubiquiti"],
        [
            "PoE Injector",
            "Patch Panel 24-Port",
            "Media Converter",
            "Rack Mount 12U",
            "Fiber Patch Cord",
            "Network Tester",
        ],
        (900, 18000),
    ),
    "Safety & PPE": (
        ["Karam", "3M", "Honeywell", "Venus", "Udyogi"],
        [
            "Safety Goggles",
            "Ear Plugs Box",
            "Respirator Mask",
            "Safety Shoes",
            "Face Shield",
            "Fall Arrest Harness",
        ],
        (150, 4500),
    ),
    "Packaging": (
        ["PackRight", "Uline", "Sealed Air", "Avery"],
        [
            "Shipping Labels 1000pc",
            "Void Fill Paper",
            "Edge Protectors",
            "Poly Mailer Pack",
            "Strapping Roll",
            "Desiccant Sachets",
        ],
        (200, 2200),
    ),
}

TARGET_PRODUCTS = 200

CATEGORY_SUPPLIER = {
    "Electronics": [0, 1, 2],
    "Office Supplies": [3, 4],
    "Furniture": [4, 3],
    "Networking": [2, 5],
    "Safety & PPE": [6],
    "Packaging": [7],
}

# Indian retail rhythm: festive build-up Sep-Nov, slump in Jan-Feb.
SEASONAL = {
    1: 0.75,
    2: 0.80,
    3: 1.00,
    4: 0.95,
    5: 0.90,
    6: 0.95,
    7: 1.00,
    8: 1.05,
    9: 1.20,
    10: 1.45,
    11: 1.35,
    12: 1.10,
}


def build_catalogue() -> list[tuple]:
    """Hero products plus generated variants, up to TARGET_PRODUCTS."""
    products = list(HERO_PRODUCTS)
    seen = {p[0] for p in products}
    prefix = {
        "Electronics": "ELEC",
        "Office Supplies": "OFFC",
        "Furniture": "FURN",
        "Networking": "NETW",
        "Safety & PPE": "SAFE",
        "Packaging": "PACK",
    }

    categories = list(VARIANT_TEMPLATES)
    counter = 100
    while len(products) < TARGET_PRODUCTS:
        category = categories[len(products) % len(categories)]
        brands, items, (lo, hi) = VARIANT_TEMPLATES[category]
        brand = RNG.choice(brands)
        item = RNG.choice(items)
        counter += 1
        sku = f"{prefix[category]}-{item[:3].upper()}-{counter:03d}"
        if sku in seen:
            continue
        seen.add(sku)
        cost = round(RNG.uniform(lo, hi), -1)
        products.append(
            (
                sku,
                f"{brand} {item}",
                category,
                cost,
                round(cost * RNG.uniform(1.45, 2.1), -1),
            )
        )
    return products


# ===========================================================================
# Demand model
# ===========================================================================
def daily_rates(rank: int, n_products: int, days: int, start: date) -> np.ndarray:
    """Expected units/day for one product over the simulation window.

    Zipf by popularity rank, modulated by season, weekday and a growth trend.
    """
    # Zipf, softened. A pure 1/rank curve is steeper than real catalogues and
    # collapses everything below the top few products into noise.
    base = 14.0 / (rank**0.85)

    rates = np.empty(days, dtype=float)
    for i in range(days):
        day = start + timedelta(days=i)
        seasonal = SEASONAL[day.month]
        weekday = 0.45 if day.weekday() >= 5 else 1.0
        growth = 1.0 + 0.18 * (i / days)  # ~18% year-on-year
        rates[i] = base * seasonal * weekday * growth
    return rates


def apply_anomalies(rates: np.ndarray, rank: int, days: int) -> list[str]:
    """Inject three deliberate anomalies for the week-5 detector to find."""
    injected = []
    # 1. Demand spike — a viral moment on a mid-tier product.
    if rank == 15:
        s = days - 60
        rates[s : s + 4] *= 12.0
        injected.append("demand spike")
    # 2. Sudden stall — an A-class product stops selling (supply/listing issue).
    if rank == 4:
        rates[days - 45 :] = 0.0
        injected.append("demand stall")
    return injected


# ===========================================================================
# Simulation
# ===========================================================================
def simulate_line(product, warehouse_id, rank, n_products, days, start, today):
    """Walk one (product, warehouse) forward in time.

    Returns (inventory_row, movements, sale_lines, anomalies).
    Stock depletes with demand and is replenished when it crosses the reorder
    point, so the closing quantity is a consequence of the year, not a guess.
    """
    rates = daily_rates(rank, n_products, days, start)
    anomalies = apply_anomalies(rates, rank, days)
    demand = NP_RNG.poisson(rates)

    avg_daily = float(rates.mean())
    # Two weeks of cover, floored so slow movers still have a sane threshold.
    reorder_point = max(5, math.ceil(avg_daily * 14))
    order_qty = max(20, math.ceil(avg_daily * 45))  # ~6 weeks per delivery

    inventory_id = uuid.uuid4()
    qty = order_qty + RNG.randint(0, order_qty // 2)  # opening stock

    movements, sale_lines = [], []
    pending_delivery = None  # (arrive_day, qty) — suppliers are not instant

    for i in range(days):
        day = start + timedelta(days=i)
        ts = datetime.combine(
            day, datetime.min.time(), tzinfo=timezone.utc
        ) + timedelta(hours=RNG.randint(9, 18), minutes=RNG.randint(0, 59))

        # Stock arriving from a previous reorder.
        if pending_delivery and pending_delivery[0] == i:
            qty += pending_delivery[1]
            movements.append(
                dict(
                    id=uuid.uuid4(),
                    inventory_id=inventory_id,
                    movement_type="po_delivery",
                    quantity_change=pending_delivery[1],
                    quantity_after=qty,
                    reference_id="seed:po",
                    created_at=ts,
                )
            )
            pending_delivery = None

        want = int(demand[i])
        if want > 0 and qty > 0:
            sold = min(want, qty)
            qty -= sold
            movements.append(
                dict(
                    id=uuid.uuid4(),
                    inventory_id=inventory_id,
                    movement_type="sale",
                    quantity_change=-sold,
                    quantity_after=qty,
                    reference_id="seed:sale",
                    created_at=ts,
                )
            )
            sale_lines.append((day, warehouse_id, product, sold, ts))

        # Reorder when we dip under the threshold and nothing is already inbound.
        if qty <= reorder_point and pending_delivery is None and i < days - 6:
            lead_time = RNG.randint(3, 10)
            pending_delivery = (i + lead_time, order_qty)

    inventory_row = dict(
        id=inventory_id,
        product_id=product["id"],
        warehouse_id=warehouse_id,
        quantity=qty,
        reorder_point=reorder_point,
        last_counted_at=today,
    )
    return inventory_row, movements, sale_lines, anomalies


# ===========================================================================
# Seeding
# ===========================================================================
def seed_tenant(session, company, users, days, catalogue, warehouse_defs, is_primary):
    today = datetime.now(timezone.utc)
    start = (today - timedelta(days=days)).date()

    warehouses = [
        dict(
            id=uuid.uuid4(),
            company_id=company["id"],
            name=n,
            location_code=f"{code}-{company['tag']}",
            capacity_units=cap,
            is_active=True,
        )
        for n, code, cap in warehouse_defs
    ]
    session.execute(insert(Warehouse), warehouses)

    suppliers = [
        dict(
            id=uuid.uuid4(),
            company_id=company["id"],
            name=n,
            contact_email=e,
            reliability_score=r,
            is_active=True,
        )
        for n, e, r in SUPPLIERS
    ]
    session.execute(insert(Supplier), suppliers)

    customers = [
        dict(id=uuid.uuid4(), company_id=company["id"], name=n, email=e, is_active=True)
        for n, e in CUSTOMERS
    ]
    session.execute(insert(Customer), customers)

    products = [
        dict(
            id=uuid.uuid4(),
            company_id=company["id"],
            sku=f"{sku}-{company['tag']}",
            name=name,
            category=cat,
            unit_cost=cost,
            selling_price=price,
            status="active",
            created_at=today,
            updated_at=today,
        )
        for sku, name, cat, cost, price in catalogue
    ]
    session.execute(insert(Product), products)
    session.flush()

    # --- simulate -----------------------------------------------------------
    inventory_rows, movements, sale_lines = [], [], []
    anomalies_found = []

    # Popularity is assigned independently of price. A cheap cable can be the
    # fastest mover and an expensive firewall can sell twice a year — which is
    # what real catalogues look like, and what makes the Pareto curve realistic
    # rather than a cliff.
    popularity = list(range(1, len(products) + 1))
    RNG.shuffle(popularity)

    for product, rank in zip(products, popularity):
        # Popular products are stocked in more locations.
        n_locations = 3 if rank <= 25 else (2 if rank <= 90 else 1)
        for warehouse in RNG.sample(warehouses, min(n_locations, len(warehouses))):
            inv, movs, lines, anoms = simulate_line(
                product, warehouse["id"], rank, len(products), days, start, today
            )
            inventory_rows.append(inv)
            movements.extend(movs)
            sale_lines.extend(lines)
            if anoms and not any(a[0] == product["sku"] for a in anomalies_found):
                # One entry per product, not one per warehouse line.
                anomalies_found.append((product["sku"], anoms))

    session.execute(insert(Inventory), inventory_rows)

    # --- group sale lines into orders ---------------------------------------
    by_day_wh: dict[tuple, list] = {}
    for day, warehouse_id, product, qty, ts in sale_lines:
        by_day_wh.setdefault((day, warehouse_id), []).append((product, qty, ts))

    sales, sale_items = [], []
    for (day, warehouse_id), lines in by_day_wh.items():
        RNG.shuffle(lines)
        while lines:
            basket = [lines.pop() for _ in range(min(RNG.randint(1, 4), len(lines)))]
            sale_id = uuid.uuid4()
            total = sum(float(p["selling_price"]) * q for p, q, _ in basket)
            sales.append(
                dict(
                    id=sale_id,
                    company_id=company["id"],
                    customer_id=RNG.choice(customers)["id"],
                    source_warehouse_id=warehouse_id,
                    status="completed",
                    total_amount=round(total, 2),
                    created_at=basket[0][2],
                )
            )
            sale_items.extend(
                dict(
                    id=uuid.uuid4(),
                    sale_id=sale_id,
                    product_id=p["id"],
                    quantity=q,
                    unit_price=p["selling_price"],
                )
                for p, q, _ in basket
            )

    for chunk_start in range(0, len(sales), 5000):
        session.execute(insert(Sale), sales[chunk_start : chunk_start + 5000])
    for chunk_start in range(0, len(sale_items), 5000):
        session.execute(insert(SaleItem), sale_items[chunk_start : chunk_start + 5000])
    for chunk_start in range(0, len(movements), 5000):
        session.execute(
            insert(InventoryMovement), movements[chunk_start : chunk_start + 5000]
        )

    # --- anomaly 3: inventory shrinkage -------------------------------------
    if is_primary:
        victim = inventory_rows[len(inventory_rows) // 3]
        loss = max(5, victim["quantity"] // 3)
        victim_new = victim["quantity"] - loss
        session.execute(
            text("UPDATE inventory SET quantity = :q WHERE id = :i"),
            {"q": victim_new, "i": victim["id"]},
        )
        session.execute(
            insert(InventoryMovement),
            [
                dict(
                    id=uuid.uuid4(),
                    inventory_id=victim["id"],
                    movement_type="manual_adjustment",
                    quantity_change=-loss,
                    quantity_after=victim_new,
                    reference_id="Reason: stock count discrepancy - suspected shrinkage",
                    created_at=today - timedelta(days=9),
                )
            ],
        )
        anomalies_found.append(("<shrinkage>", [f"-{loss} units unexplained"]))

    # --- one open purchase order so the PO screen is not empty --------------
    po_id = uuid.uuid4()
    session.execute(
        insert(PurchaseOrder),
        [
            dict(
                id=po_id,
                company_id=company["id"],
                supplier_id=suppliers[0]["id"],
                destination_warehouse_id=warehouses[0]["id"],
                status="draft",
                expected_delivery_date=(today + timedelta(days=12)).date(),
                total_amount=0,
                created_at=today - timedelta(days=2),
            )
        ],
    )
    po_products = products[:4]
    session.execute(
        insert(POItem),
        [
            dict(
                id=uuid.uuid4(),
                po_id=po_id,
                product_id=p["id"],
                quantity=50,
                unit_price=p["unit_cost"],
            )
            for p in po_products
        ],
    )
    session.execute(
        text("UPDATE purchase_orders SET total_amount = :t WHERE id = :i"),
        {"t": sum(float(p["unit_cost"]) * 50 for p in po_products), "i": po_id},
    )

    return dict(
        products=len(products),
        warehouses=len(warehouses),
        inventory=len(inventory_rows),
        sales=len(sales),
        sale_items=len(sale_items),
        movements=len(movements),
        anomalies=anomalies_found,
    )


def wipe(session):
    """Clear every application table.

    TRUNCATE ... CASCADE rather than hand-ordered DELETEs: it resolves foreign
    key order itself, so this keeps working when new tables are added. Hand
    ordering silently breaks the moment someone adds a table and forgets here.
    RESTART IDENTITY also resets the outbox sequence back to 1.
    """
    tables = (
        session.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        )
        .scalars()
        .all()
    )
    if tables:
        session.execute(
            text(f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE")
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="wipe existing data first")
    args = parser.parse_args()

    url = os.getenv(
        "DATABASE_URL",
        "postgresql://optistock:optistock_password@127.0.0.1:5433/optistock_db",
    )
    print(f"-> {url.rsplit('@', 1)[-1]}")

    engine = create_engine(url)
    Session = sessionmaker(bind=engine)
    session = Session()
    started = datetime.now()

    try:
        existing = session.execute(text("SELECT count(*) FROM companies")).scalar()
        if existing and not args.reset:
            print(
                f"\n  {existing} companies already present. Use --reset to wipe and re-seed."
            )
            return 1
        if args.reset:
            print("  wiping...")
            wipe(session)
            session.commit()

        catalogue = build_catalogue()

        # --- Tenant A: the demo tenant ------------------------------------
        company_a = dict(
            id=uuid.uuid4(),
            name="TechNova Industries",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            tag="A",
        )
        # --- Tenant B: exists so isolation is demonstrable, deliberately small
        company_b = dict(
            id=uuid.uuid4(),
            name="GreenLeaf Supply Co.",
            is_active=True,
            created_at=datetime.now(timezone.utc),
            tag="B",
        )

        session.execute(
            insert(Company),
            [
                {k: v for k, v in c.items() if k != "tag"}
                for c in (company_a, company_b)
            ],
        )

        users = []
        for company, domain in (
            (company_a, "technova.com"),
            (company_b, "greenleaf.com"),
        ):
            for role in ("admin", "warehouse_manager", "sales_rep", "analyst"):
                users.append(
                    dict(
                        id=uuid.uuid4(),
                        company_id=company["id"],
                        email=f"{role.split('_')[0]}@{domain}",
                        hashed_password=pwd_context.hash(DEMO_PASSWORD),
                        role=role,
                        is_active=True,
                        failed_login_attempts=0,
                        created_at=datetime.now(timezone.utc),
                    )
                )
        session.execute(insert(User), users)
        session.flush()

        print(
            f"\n  Tenant A - simulating {SIM_DAYS} days across {TARGET_PRODUCTS} products..."
        )
        stats_a = seed_tenant(
            session, company_a, users, SIM_DAYS, catalogue, WAREHOUSES, is_primary=True
        )

        print(f"  Tenant B - simulating {TENANT_B_DAYS} days (isolation demo)...")
        stats_b = seed_tenant(
            session,
            company_b,
            users,
            TENANT_B_DAYS,
            catalogue[:25],
            WAREHOUSES[:1],
            is_primary=False,
        )

        session.commit()

        # --- report ---------------------------------------------------------
        low = session.execute(
            text(
                "SELECT count(*) FROM inventory WHERE quantity <= reorder_point AND reorder_point > 0"
            )
        ).scalar()
        out = session.execute(
            text("SELECT count(*) FROM inventory WHERE quantity = 0")
        ).scalar()

        print(f"\n{'':-<60}")
        for label, s in (
            ("Tenant A (TechNova)", stats_a),
            ("Tenant B (GreenLeaf)", stats_b),
        ):
            print(f"  {label}")
            print(
                f"    products {s['products']:>5}   warehouses {s['warehouses']:>2}   "
                f"stock lines {s['inventory']:>5}"
            )
            print(
                f"    sales    {s['sales']:>5}   items      {s['sale_items']:>5}   "
                f"movements   {s['movements']:>5}"
            )
        print(f"\n  below reorder point: {low}   at zero: {out}")
        print("\n  anomalies planted (for week-5 detection):")
        for sku, kinds in stats_a["anomalies"]:
            print(f"    {sku:<22} {', '.join(kinds)}")
        print(f"\n  login: admin@technova.com / {DEMO_PASSWORD}")
        print(f"  took {(datetime.now() - started).total_seconds():.1f}s")
        print(f"{'':-<60}")
        print("\n  next: run the ETL so ABC classes and recommendations exist.")
        return 0

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
