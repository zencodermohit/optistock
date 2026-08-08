"""
OptiStock Enterprise - Comprehensive Database Seeder
=====================================================
Generates realistic, enterprise-grade inventory data across ALL tables to
power impressive Power BI dashboards.

Data Overview:
 - 2 Companies (multi-tenant demonstration)
 - 5 Warehouses across different regions
 - 30 Products across 6 categories with realistic pricing
 - 8 Suppliers with varied reliability scores
 - 10 Customers (B2B)
 - ~500+ Sales spanning 12 months with seasonal trends
 - ~120 Purchase Orders with delivery lifecycle
 - Inventory records with realistic stock levels
 - Inventory Movements (audit trail)
 - Inter-warehouse Transfers
 - Stock Reconciliations

Usage:
  1. Ensure Docker is running: docker compose up -d
  2. Activate venv: .\\venv\\Scripts\\activate
  3. Run: python seed_db.py
"""

import uuid
import random
import os
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal

# Override DATABASE_URL before importing app modules so the seed script
# connects to the Docker-mapped port on localhost instead of the internal
# Docker hostname "db" which is unreachable from the host machine.
os.environ["DATABASE_URL"] = "postgresql://optistock:optistock_password@localhost:5433/optistock_db"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.modules.companies.models import Company
from app.modules.warehouses.models import Warehouse
from app.modules.products.models import Product
from app.modules.inventory.models import Inventory, InventoryMovement
from app.modules.suppliers.models import Supplier
from app.modules.purchase_orders.models import PurchaseOrder, POItem
from app.modules.sales.models import Customer, Sale, SaleItem
from app.modules.transfers.models import Transfer, TransferItem
from app.modules.reconciliation.models import Reconciliation, ReconciliationItem
from app.modules.users.models import User

# For hashing the demo user password
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Create a direct connection to the host-mapped port
engine = create_engine("postgresql://optistock:optistock_password@localhost:5433/optistock_db")
SessionLocal = sessionmaker(bind=engine)

# ============================================================
# REALISTIC DATA DEFINITIONS
# ============================================================

COMPANIES = [
    {"name": "TechNova Industries", "is_active": True},
    {"name": "GreenLeaf Supply Co.", "is_active": True},
]

WAREHOUSES = [
    {"name": "Mumbai Central Hub", "location_code": "WH-MUM-001", "capacity_units": 50000},
    {"name": "Delhi Distribution Center", "location_code": "WH-DEL-002", "capacity_units": 35000},
    {"name": "Bangalore Tech Park", "location_code": "WH-BLR-003", "capacity_units": 25000},
    {"name": "Chennai Port Facility", "location_code": "WH-CHN-004", "capacity_units": 40000},
    {"name": "Hyderabad Fulfillment Center", "location_code": "WH-HYD-005", "capacity_units": 30000},
]

# 30 Products across 6 categories with realistic Indian market pricing
PRODUCTS = [
    # Electronics (6 products)
    {"sku": "ELEC-LAP-001", "name": "ProBook Laptop 15\" i7", "category": "Electronics", "unit_cost": 45000.00, "selling_price": 72999.00},
    {"sku": "ELEC-MON-002", "name": "UltraView 27\" 4K Monitor", "category": "Electronics", "unit_cost": 18000.00, "selling_price": 28999.00},
    {"sku": "ELEC-TAB-003", "name": "SmartTab Pro 11\" Tablet", "category": "Electronics", "unit_cost": 22000.00, "selling_price": 34999.00},
    {"sku": "ELEC-PHN-004", "name": "NovaPix 5G Smartphone", "category": "Electronics", "unit_cost": 15000.00, "selling_price": 24999.00},
    {"sku": "ELEC-EAR-005", "name": "SoundWave ANC Earbuds", "category": "Electronics", "unit_cost": 2500.00, "selling_price": 4999.00},
    {"sku": "ELEC-CHR-006", "name": "RapidCharge 65W Adapter", "category": "Electronics", "unit_cost": 800.00, "selling_price": 1499.00},

    # Office Supplies (5 products)
    {"sku": "OFFC-PPR-001", "name": "Premium A4 Paper (500 sheets)", "category": "Office Supplies", "unit_cost": 180.00, "selling_price": 349.00},
    {"sku": "OFFC-PEN-002", "name": "Executive Ballpoint Pen Set", "category": "Office Supplies", "unit_cost": 250.00, "selling_price": 599.00},
    {"sku": "OFFC-BND-003", "name": "Leather Document Binder", "category": "Office Supplies", "unit_cost": 400.00, "selling_price": 899.00},
    {"sku": "OFFC-DSK-004", "name": "Ergonomic Desk Organizer", "category": "Office Supplies", "unit_cost": 650.00, "selling_price": 1299.00},
    {"sku": "OFFC-WHB-005", "name": "Magnetic Whiteboard 4x3ft", "category": "Office Supplies", "unit_cost": 1200.00, "selling_price": 2499.00},

    # Furniture (5 products)
    {"sku": "FURN-CHR-001", "name": "ErgoMax Office Chair", "category": "Furniture", "unit_cost": 8500.00, "selling_price": 14999.00},
    {"sku": "FURN-DSK-002", "name": "Standing Desk Pro 60\"", "category": "Furniture", "unit_cost": 12000.00, "selling_price": 21999.00},
    {"sku": "FURN-CAB-003", "name": "Steel Filing Cabinet 4-Drawer", "category": "Furniture", "unit_cost": 5500.00, "selling_price": 9999.00},
    {"sku": "FURN-SHL-004", "name": "Modular Bookshelf Unit", "category": "Furniture", "unit_cost": 3200.00, "selling_price": 5999.00},
    {"sku": "FURN-TBL-005", "name": "Conference Table 8-Seater", "category": "Furniture", "unit_cost": 18000.00, "selling_price": 32999.00},

    # Networking Equipment (5 products)
    {"sku": "NETW-RTR-001", "name": "Enterprise WiFi 6 Router", "category": "Networking", "unit_cost": 4500.00, "selling_price": 7999.00},
    {"sku": "NETW-SWT-002", "name": "48-Port Managed Switch", "category": "Networking", "unit_cost": 12000.00, "selling_price": 19999.00},
    {"sku": "NETW-CBL-003", "name": "Cat6 Ethernet Cable (100m)", "category": "Networking", "unit_cost": 1800.00, "selling_price": 3499.00},
    {"sku": "NETW-AP-004", "name": "Ceiling Mount Access Point", "category": "Networking", "unit_cost": 6000.00, "selling_price": 10999.00},
    {"sku": "NETW-FWL-005", "name": "Next-Gen Firewall Appliance", "category": "Networking", "unit_cost": 35000.00, "selling_price": 59999.00},

    # Safety & PPE (4 products)
    {"sku": "SAFE-HLM-001", "name": "Industrial Safety Helmet", "category": "Safety & PPE", "unit_cost": 350.00, "selling_price": 699.00},
    {"sku": "SAFE-GLV-002", "name": "Cut-Resistant Work Gloves", "category": "Safety & PPE", "unit_cost": 180.00, "selling_price": 399.00},
    {"sku": "SAFE-VST-003", "name": "Hi-Vis Reflective Vest", "category": "Safety & PPE", "unit_cost": 220.00, "selling_price": 499.00},
    {"sku": "SAFE-KIT-004", "name": "First Aid Kit Industrial", "category": "Safety & PPE", "unit_cost": 900.00, "selling_price": 1799.00},

    # Packaging (5 products)
    {"sku": "PACK-BOX-001", "name": "Corrugated Box (Pack of 50)", "category": "Packaging", "unit_cost": 600.00, "selling_price": 1199.00},
    {"sku": "PACK-TPE-002", "name": "Heavy-Duty Packing Tape (12 rolls)", "category": "Packaging", "unit_cost": 350.00, "selling_price": 699.00},
    {"sku": "PACK-WRP-003", "name": "Bubble Wrap Roll 100m", "category": "Packaging", "unit_cost": 450.00, "selling_price": 899.00},
    {"sku": "PACK-PLT-004", "name": "Wooden Pallet (Standard)", "category": "Packaging", "unit_cost": 800.00, "selling_price": 1499.00},
    {"sku": "PACK-STR-005", "name": "Stretch Film Roll 500mm", "category": "Packaging", "unit_cost": 280.00, "selling_price": 549.00},
]

SUPPLIERS = [
    {"name": "Reliance Digital Wholesale", "contact_email": "wholesale@reliancedigital.in", "reliability_score": 0.95},
    {"name": "Tata Components Ltd", "contact_email": "supply@tatacomponents.com", "reliability_score": 0.98},
    {"name": "Wipro Peripherals", "contact_email": "orders@wiproperipherals.in", "reliability_score": 0.88},
    {"name": "Mahindra Logistics Supply", "contact_email": "vendor@mahindralogistics.com", "reliability_score": 0.92},
    {"name": "Godrej Interio B2B", "contact_email": "b2b@godrejinterio.com", "reliability_score": 0.97},
    {"name": "D-Link India Partners", "contact_email": "partners@dlink.co.in", "reliability_score": 0.85},
    {"name": "Karam Safety Distributors", "contact_email": "sales@karamsafety.in", "reliability_score": 0.90},
    {"name": "PackRight Industries", "contact_email": "orders@packright.in", "reliability_score": 0.82},
]

CUSTOMERS = [
    {"name": "Infosys Technologies", "email": "procurement@infosys.com"},
    {"name": "Wipro Limited", "email": "supplies@wipro.com"},
    {"name": "HCL Technologies", "email": "orders@hcltech.com"},
    {"name": "Tech Mahindra", "email": "buying@techmahindra.com"},
    {"name": "L&T InfoTech", "email": "purchase@ltimindtree.com"},
    {"name": "Bajaj Finance Ltd", "email": "admin@bajajfinance.in"},
    {"name": "HDFC Bank Operations", "email": "facilities@hdfcbank.com"},
    {"name": "Flipkart Pvt Ltd", "email": "warehouse@flipkart.com"},
    {"name": "Zomato Corporate", "email": "office@zomato.com"},
    {"name": "PhonePe India", "email": "infra@phonepe.com"},
]

# Category-to-supplier mapping (which suppliers supply which categories)
CATEGORY_SUPPLIER_MAP = {
    "Electronics": [0, 1, 2],       # Reliance, Tata, Wipro
    "Office Supplies": [3, 4],       # Mahindra, Godrej
    "Furniture": [4, 3],             # Godrej, Mahindra
    "Networking": [2, 5],            # Wipro, D-Link
    "Safety & PPE": [6],             # Karam
    "Packaging": [7],                # PackRight
}

# Seasonal multipliers for sales (indexed by month 1-12)
# Higher in Oct-Dec (festive/holiday), lower in Jan-Feb
SEASONAL_MULTIPLIERS = {
    1: 0.6,   # January (post-holiday lull)
    2: 0.7,   # February
    3: 0.85,  # March (financial year-end rush)
    4: 0.75,  # April
    5: 0.8,   # May
    6: 0.85,  # June
    7: 0.9,   # July
    8: 0.95,  # August
    9: 1.0,   # September
    10: 1.3,  # October (Diwali season starts)
    11: 1.5,  # November (Diwali + Black Friday)
    12: 1.4,  # December (Christmas + Year-end)
}


def random_date_in_month(year: int, month: int) -> datetime:
    """Generate a random datetime within a specific month."""
    if month == 12:
        max_day = 31
    else:
        next_month_start = date(year, month + 1, 1)
        max_day = (next_month_start - timedelta(days=1)).day
    day = random.randint(1, max_day)
    hour = random.randint(8, 20)  # Business hours
    minute = random.randint(0, 59)
    return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


def generate_comprehensive_data():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("  OptiStock Enterprise - Comprehensive Data Seeder")
        print("=" * 60)

        # =========================================================
        # 1. COMPANIES
        # =========================================================
        print("\n[1/11] Creating companies...")
        company_objs = []
        for c_data in COMPANIES:
            company = Company(id=uuid.uuid4(), **c_data)
            db.add(company)
            company_objs.append(company)
        db.flush()
        print(f"       âœ“ Created {len(company_objs)} companies")

        # We'll use the first company for the main dataset
        main_company = company_objs[0]
        secondary_company = company_objs[1]

        # =========================================================
        # 2. WAREHOUSES
        # =========================================================
        print("\n[2/11] Creating warehouses...")
        warehouse_objs = []
        for wh_data in WAREHOUSES:
            wh = Warehouse(
                id=uuid.uuid4(),
                company_id=main_company.id,
                is_active=True,
                **wh_data,
            )
            db.add(wh)
            warehouse_objs.append(wh)
        # Add 2 warehouses for secondary company
        for i, wh_data in enumerate(WAREHOUSES[:2]):
            wh = Warehouse(
                id=uuid.uuid4(),
                company_id=secondary_company.id,
                name=f"GL-{wh_data['name']}",
                location_code=f"GL-{wh_data['location_code']}",
                capacity_units=wh_data["capacity_units"],
                is_active=True,
            )
            db.add(wh)
        db.flush()
        print(f"       âœ“ Created {len(WAREHOUSES) + 2} warehouses")

        # =========================================================
        # 3. PRODUCTS
        # =========================================================
        print("\n[3/11] Creating products...")
        product_objs = []
        for p_data in PRODUCTS:
            # Stagger the created_at dates to show product launch timeline
            product = Product(
                id=uuid.uuid4(),
                company_id=main_company.id,
                sku=p_data["sku"],
                name=p_data["name"],
                category=p_data["category"],
                unit_cost=Decimal(str(p_data["unit_cost"])),
                selling_price=Decimal(str(p_data["selling_price"])),
                status="active",
                created_at=datetime(2025, random.randint(1, 6), random.randint(1, 28), tzinfo=timezone.utc),
            )
            db.add(product)
            product_objs.append(product)
        db.flush()
        print(f"       âœ“ Created {len(product_objs)} products across {len(set(p['category'] for p in PRODUCTS))} categories")

        # =========================================================
        # 4. SUPPLIERS
        # =========================================================
        print("\n[4/11] Creating suppliers...")
        supplier_objs = []
        for s_data in SUPPLIERS:
            supplier = Supplier(
                id=uuid.uuid4(),
                company_id=main_company.id,
                name=s_data["name"],
                contact_email=s_data["contact_email"],
                reliability_score=Decimal(str(s_data["reliability_score"])),
                is_active=True,
            )
            db.add(supplier)
            supplier_objs.append(supplier)
        db.flush()
        print(f"       âœ“ Created {len(supplier_objs)} suppliers")

        # =========================================================
        # 5. CUSTOMERS
        # =========================================================
        print("\n[5/11] Creating customers...")
        customer_objs = []
        for cust_data in CUSTOMERS:
            customer = Customer(
                id=uuid.uuid4(),
                company_id=main_company.id,
                name=cust_data["name"],
                email=cust_data["email"],
                is_active=True,
            )
            db.add(customer)
            customer_objs.append(customer)
        db.flush()
        print(f"       âœ“ Created {len(customer_objs)} customers")

        # =========================================================
        # 6. USERS (Demo accounts)
        # =========================================================
        print("\n[6/11] Creating demo users...")
        demo_users = [
            {"email": "admin@technova.com", "role": "admin"},
            {"email": "warehouse@technova.com", "role": "warehouse_manager"},
            {"email": "sales@technova.com", "role": "sales_rep"},
            {"email": "analyst@technova.com", "role": "analyst"},
        ]
        for u_data in demo_users:
            user = User(
                id=uuid.uuid4(),
                company_id=main_company.id,
                email=u_data["email"],
                hashed_password=pwd_context.hash("Demo@12345"),
                role=u_data["role"],
                is_active=True,
            )
            db.add(user)
        db.flush()
        print(f"       âœ“ Created {len(demo_users)} demo users (password: Demo@12345)")

        # =========================================================
        # 7. INVENTORY (Initial stock levels)
        # =========================================================
        print("\n[7/11] Setting up inventory across warehouses...")
        inventory_objs = {}  # (product_id, warehouse_id) -> Inventory
        inv_count = 0
        for product in product_objs:
            # Not every product is in every warehouse
            num_warehouses = random.randint(2, len(warehouse_objs))
            selected_warehouses = random.sample(warehouse_objs, num_warehouses)
            for wh in selected_warehouses:
                # Higher stock for cheaper items, lower for expensive items
                cost = float(product.unit_cost)
                if cost < 500:
                    base_qty = random.randint(200, 800)
                elif cost < 5000:
                    base_qty = random.randint(50, 300)
                elif cost < 20000:
                    base_qty = random.randint(15, 80)
                else:
                    base_qty = random.randint(5, 30)

                inv = Inventory(
                    id=uuid.uuid4(),
                    product_id=product.id,
                    warehouse_id=wh.id,
                    quantity=base_qty,
                    last_counted_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
                )
                db.add(inv)
                inventory_objs[(product.id, wh.id)] = inv
                inv_count += 1
        db.flush()
        print(f"       âœ“ Created {inv_count} inventory records")

        # =========================================================
        # 8. PURCHASE ORDERS (12 months of inbound supply)
        # =========================================================
        print("\n[8/11] Generating 12 months of purchase orders...")
        po_count = 0
        po_item_count = 0
        movement_count = 0

        # Group products by category for smart supplier assignment
        products_by_category = {}
        for p in product_objs:
            products_by_category.setdefault(p.category, []).append(p)

        for month in range(1, 13):
            # 8-15 POs per month
            num_pos = random.randint(8, 15)
            for _ in range(num_pos):
                # Pick a category, then pick a valid supplier for that category
                category = random.choice(list(CATEGORY_SUPPLIER_MAP.keys()))
                supplier_idx = random.choice(CATEGORY_SUPPLIER_MAP[category])
                supplier = supplier_objs[supplier_idx]
                dest_wh = random.choice(warehouse_objs)

                po_date = random_date_in_month(2026, month)
                lead_days = random.randint(3, 21)
                expected_delivery = (po_date + timedelta(days=lead_days)).date()

                # Determine status based on reliability and timing
                reliability = float(supplier.reliability_score)
                if month <= 6:
                    # Past months: mostly delivered
                    roll = random.random()
                    if roll < reliability:
                        status = "delivered"
                    elif roll < 0.95:
                        status = "delivered"  # Late but delivered
                    else:
                        status = "cancelled"
                elif month <= 8:
                    status = random.choice(["delivered", "delivered", "submitted"])
                else:
                    status = random.choice(["submitted", "draft", "delivered"])

                po = PurchaseOrder(
                    id=uuid.uuid4(),
                    company_id=main_company.id,
                    supplier_id=supplier.id,
                    destination_warehouse_id=dest_wh.id,
                    status=status,
                    expected_delivery_date=expected_delivery,
                    total_amount=Decimal("0"),
                    created_at=po_date,
                )
                db.add(po)
                db.flush()

                # Add 1-4 line items from the matching category
                available_products = products_by_category.get(category, product_objs[:5])
                num_items = random.randint(1, min(4, len(available_products)))
                selected_products = random.sample(available_products, num_items)

                po_total = Decimal("0")
                for prod in selected_products:
                    qty = random.randint(10, 100)
                    unit_price = prod.unit_cost * Decimal("0.9")  # Slight wholesale discount

                    po_item = POItem(
                        id=uuid.uuid4(),
                        po_id=po.id,
                        product_id=prod.id,
                        quantity=qty,
                        unit_price=unit_price,
                    )
                    db.add(po_item)
                    po_total += unit_price * qty
                    po_item_count += 1

                    # If delivered, create inventory movement
                    if status == "delivered":
                        inv_key = (prod.id, dest_wh.id)
                        if inv_key in inventory_objs:
                            inv = inventory_objs[inv_key]
                            old_qty = inv.quantity
                            inv.quantity += qty
                            movement = InventoryMovement(
                                id=uuid.uuid4(),
                                inventory_id=inv.id,
                                movement_type="po_delivery",
                                quantity_change=qty,
                                quantity_after=inv.quantity,
                                reference_id=str(po.id),
                                created_at=po_date + timedelta(days=lead_days),
                            )
                            db.add(movement)
                            movement_count += 1

                po.total_amount = po_total
                po_count += 1

        db.flush()
        print(f"       âœ“ Created {po_count} purchase orders with {po_item_count} line items")

        # =========================================================
        # 9. SALES (12 months with seasonal trends)
        # =========================================================
        print("\n[9/11] Generating 12 months of sales with seasonal trends...")
        sale_count = 0
        sale_item_count = 0

        for month in range(1, 13):
            multiplier = SEASONAL_MULTIPLIERS[month]
            # Base of 30-50 sales/month, adjusted by seasonal multiplier
            num_sales = int(random.randint(30, 50) * multiplier)

            for _ in range(num_sales):
                customer = random.choice(customer_objs)
                source_wh = random.choice(warehouse_objs)
                sale_date = random_date_in_month(2026, month)

                sale = Sale(
                    id=uuid.uuid4(),
                    company_id=main_company.id,
                    customer_id=customer.id,
                    source_warehouse_id=source_wh.id,
                    status="completed",
                    total_amount=Decimal("0"),
                    created_at=sale_date,
                )
                db.add(sale)
                db.flush()

                # Each sale has 1-5 items
                num_items = random.choices([1, 2, 3, 4, 5], weights=[25, 35, 20, 12, 8])[0]
                selected_products = random.sample(product_objs, min(num_items, len(product_objs)))

                sale_total = Decimal("0")
                for prod in selected_products:
                    # Higher quantity for cheaper items
                    cost = float(prod.selling_price)
                    if cost < 1000:
                        qty = random.randint(5, 50)
                    elif cost < 10000:
                        qty = random.randint(2, 15)
                    elif cost < 30000:
                        qty = random.randint(1, 5)
                    else:
                        qty = random.randint(1, 3)

                    sale_item = SaleItem(
                        id=uuid.uuid4(),
                        sale_id=sale.id,
                        product_id=prod.id,
                        quantity=qty,
                        unit_price=prod.selling_price,
                    )
                    db.add(sale_item)
                    sale_total += prod.selling_price * qty
                    sale_item_count += 1

                    # Deduct from inventory (create movement)
                    inv_key = (prod.id, source_wh.id)
                    if inv_key in inventory_objs:
                        inv = inventory_objs[inv_key]
                        if inv.quantity >= qty:
                            inv.quantity -= qty
                            movement = InventoryMovement(
                                id=uuid.uuid4(),
                                inventory_id=inv.id,
                                movement_type="sale",
                                quantity_change=-qty,
                                quantity_after=inv.quantity,
                                reference_id=str(sale.id),
                                created_at=sale_date,
                            )
                            db.add(movement)
                            movement_count += 1

                sale.total_amount = sale_total
                sale_count += 1

        db.flush()
        print(f"       âœ“ Created {sale_count} sales with {sale_item_count} line items")
        print(f"       âœ“ Created {movement_count} inventory movements (audit trail)")

        # =========================================================
        # 10. INTER-WAREHOUSE TRANSFERS
        # =========================================================
        print("\n[10/11] Generating inter-warehouse transfers...")
        transfer_count = 0
        for month in range(1, 13):
            # 2-5 transfers per month (rebalancing stock)
            num_transfers = random.randint(2, 5)
            for _ in range(num_transfers):
                src, dst = random.sample(warehouse_objs, 2)
                transfer_date = random_date_in_month(2026, month)

                statuses = ["completed", "completed", "completed", "in_transit", "pending"]
                if month <= 6:
                    status = "completed"
                else:
                    status = random.choice(statuses)

                transfer = Transfer(
                    id=uuid.uuid4(),
                    company_id=main_company.id,
                    source_warehouse_id=src.id,
                    destination_warehouse_id=dst.id,
                    status=status,
                    shipped_at=transfer_date if status != "pending" else None,
                    received_at=transfer_date + timedelta(days=random.randint(1, 3)) if status == "completed" else None,
                    created_at=transfer_date,
                )
                db.add(transfer)
                db.flush()

                # 1-3 products per transfer
                num_items = random.randint(1, 3)
                transfer_products = random.sample(product_objs, num_items)
                for prod in transfer_products:
                    qty = random.randint(5, 30)
                    t_item = TransferItem(
                        id=uuid.uuid4(),
                        transfer_id=transfer.id,
                        product_id=prod.id,
                        quantity=qty,
                    )
                    db.add(t_item)
                transfer_count += 1

        db.flush()
        print(f"       âœ“ Created {transfer_count} inter-warehouse transfers")

        # =========================================================
        # 11. STOCK RECONCILIATIONS (Quarterly cycle counts)
        # =========================================================
        print("\n[11/11] Generating quarterly stock reconciliations...")
        recon_count = 0
        for quarter_month in [3, 6, 9]:  # March, June, September
            for wh in warehouse_objs:
                recon_date = random_date_in_month(2026, quarter_month)
                recon = Reconciliation(
                    id=uuid.uuid4(),
                    company_id=main_company.id,
                    warehouse_id=wh.id,
                    status="approved" if quarter_month <= 6 else "pending",
                    created_at=recon_date,
                )
                db.add(recon)
                db.flush()

                # Check 5-10 random products per reconciliation
                products_to_check = random.sample(product_objs, min(random.randint(5, 10), len(product_objs)))
                for prod in products_to_check:
                    inv_key = (prod.id, wh.id)
                    if inv_key in inventory_objs:
                        expected = inventory_objs[inv_key].quantity
                        # 85% perfect match, 15% discrepancy
                        if random.random() < 0.85:
                            actual = expected
                            reason = None
                        else:
                            variance = random.randint(-5, -1)
                            actual = max(0, expected + variance)
                            reason = random.choice(["damaged", "lost", "data_entry_error", "theft_suspected"])

                        r_item = ReconciliationItem(
                            id=uuid.uuid4(),
                            reconciliation_id=recon.id,
                            product_id=prod.id,
                            expected_quantity=expected,
                            actual_quantity=actual,
                            discrepancy_reason=reason,
                        )
                        db.add(r_item)
                recon_count += 1

        db.flush()
        print(f"       âœ“ Created {recon_count} reconciliation reports")

        # =========================================================
        # COMMIT EVERYTHING
        # =========================================================
        db.commit()

        print("\n" + "=" * 60)
        print("  [OK] DATABASE SEEDING COMPLETE!")
        print("=" * 60)
        print(f"""
  Summary:
  ----------------------------------------
  Companies .............. {len(company_objs)}
  Warehouses ............. {len(WAREHOUSES) + 2}
  Products ............... {len(product_objs)}
  Suppliers .............. {len(supplier_objs)}
  Customers .............. {len(customer_objs)}
  Users .................. {len(demo_users)}
  Inventory Records ...... {inv_count}
  Purchase Orders ........ {po_count} ({po_item_count} items)
  Sales .................. {sale_count} ({sale_item_count} items)
  Inventory Movements .... {movement_count}
  Transfers .............. {transfer_count}
  Reconciliations ........ {recon_count}
  ----------------------------------------

  Demo Login Credentials:
  Email:    admin@technova.com
  Password: Demo@12345

  Power BI SQL Views Ready:
  - current_stock_levels_view
  - monthly_revenue_view
  - supplier_performance_view

  Connect Power BI to: localhost:5433 / optistock_db
        """)

    except Exception as e:
        db.rollback()
        print(f"\n[FAILED]: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    generate_comprehensive_data()
