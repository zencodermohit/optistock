# OptiStock — Software Requirement Specification (SRS)

> **OptiStock — Enterprise Inventory Intelligence Platform**

**Document Version:** 1.1  
**Date:** 2026-07-01  
**Author:** OptiStock Engineering Team  
**Status:** Draft — Pending Technical Review  
**Reference:** [Business Requirements Document v1.1](./01_business_requirements_document.md)

---

## 1. Introduction

### 1.1 Purpose

This document defines the complete functional and non-functional software requirements for the OptiStock platform. It serves as the authoritative reference for engineering, testing, and validation throughout the project lifecycle.

Every requirement in this document is:
- **Traceable** — linked to a business objective from the BRD
- **Testable** — can be verified through automated or manual testing
- **Unambiguous** — uses precise language with measurable criteria

### 1.2 Scope

OptiStock is a web-based, multi-tenant SaaS platform that provides:
- Centralized inventory management across multiple warehouses
- AI-powered demand forecasting and inventory optimization
- Automated data ingestion and ETL processing
- Intelligent recommendation engine for business decisions
- Role-based dashboards and analytics
- Supplier performance tracking and scoring

The system is initially built as a single-tenant application (Stages 1–4) and evolves into a multi-tenant architecture (Stage 9+). The requirements below apply to the full platform across all stages, with stage annotations where applicable.

### 1.3 Requirement ID Convention

All requirements follow a consistent naming convention:

| Prefix | Category |
|---|---|
| `FR-PM-xxx` | Product Management |
| `FR-IM-xxx` | Inventory Management |
| `FR-WH-xxx` | Warehouse Management |
| `FR-SP-xxx` | Supplier Management |
| `FR-PO-xxx` | Purchase Orders |
| `FR-SA-xxx` | Sales Management |
| `FR-CU-xxx` | Customer Management |
| `FR-AN-xxx` | Analytics and Reporting |
| `FR-ET-xxx` | ETL and Data Import |
| `FR-FC-xxx` | Forecasting |
| `FR-OP-xxx` | Inventory Optimization |
| `FR-RC-xxx` | Recommendation Engine |
| `FR-AU-xxx` | Authentication and Authorization |
| `FR-NF-xxx` | Notifications and Alerts |
| `FR-AD-xxx` | Administration |
| `FR-IR-xxx` | Inventory Reconciliation |
| `FR-BJ-xxx` | Background Jobs and Scheduling |
| `FR-SE-xxx` | System Events and Workflows |
| `NFR-xxx` | Non-Functional Requirements |

### 1.4 Requirement Priority Levels

| Priority | Meaning | Stage |
|---|---|---|
| **P0 — Critical** | Core functionality. System is unusable without it. | Stages 1–2 |
| **P1 — High** | Important feature. Needed for full product value. | Stages 3–6 |
| **P2 — Medium** | Valuable capability. Enhances the platform. | Stages 7–9 |
| **P3 — Low** | Nice to have. Can be deferred. | Stages 10–12 |

### 1.5 Definitions and Abbreviations

| Term | Definition |
|---|---|
| **Shall** | Indicates a mandatory requirement |
| **Should** | Indicates a recommended requirement |
| **May** | Indicates an optional requirement |
| **SKU** | Stock Keeping Unit |
| **EOQ** | Economic Order Quantity |
| **ROP** | Reorder Point |
| **MAPE** | Mean Absolute Percentage Error |
| **RBAC** | Role-Based Access Control |
| **JWT** | JSON Web Token |
| **CRUD** | Create, Read, Update, Delete |
| **ETL** | Extract, Transform, Load |

---

## 2. System Overview

### 2.1 System Context

```
┌──────────────────────────────────────────────────────┐
│                   External Sources                    │
│    CSV Files │ Excel │ APIs │ Manual Entry             │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│              Data Ingestion Layer                      │
│         Validation │ Cleaning │ Transformation         │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                PostgreSQL Database                    │
│     Products │ Inventory │ Sales │ Suppliers │ etc.    │
└───────┬──────────────┬───────────────┬───────────────┘
        │              │               │
        ▼              ▼               ▼
┌──────────────┐ ┌───────────┐ ┌──────────────────┐
│   FastAPI     │ │    ML     │ │  Recommendation  │
│  Backend      │ │  Engine   │ │     Engine        │
└──────┬───────┘ └─────┬─────┘ └────────┬─────────┘
       │               │                │
       └───────────────┼────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                   REST API Layer                      │
│        Authentication │ Authorization │ Routing        │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│                    Dashboard                          │
│    Executive │ Warehouse │ Supplier │ Analytics        │
└──────────────────────────────────────────────────────┘
```

### 2.2 Users and Roles

| Role | Access Level | Description |
|---|---|---|
| **Admin** | Full access | All modules, user management, system configuration |
| **Warehouse Manager** | Warehouse scope | Inventory, transfers, warehouse operations |
| **Procurement Manager** | Supplier scope | Suppliers, purchase orders, cost analysis |
| **Sales Analyst** | Read + analytics | Sales data, trends, reports |
| **Finance Manager** | Read + financial | Inventory valuation, cost reports, write-offs |
| **Supply Chain Manager** | Cross-module read + transfers | Supplier performance, logistics, warehouse coordination |
| **Executive / CEO** | Executive dashboards | KPIs, summaries, forecasts, strategic reports |

---

## 3. Functional Requirements

---

### 3.1 Product Management

**Business Context:** Products are the fundamental entity in the system. Every inventory record, sale, forecast, and recommendation references a product. The product catalog must be accurate, complete, and consistently maintained.

---

#### FR-PM-001 — Create Product
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to create a new product with the following attributes:

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | String | Yes | 1–255 characters, non-empty |
| `sku` | String | Yes | Unique across the system, alphanumeric + dashes, 3–50 characters |
| `category` | String | Yes | From predefined category list |
| `brand` | String | No | 1–100 characters |
| `description` | String | No | Max 2000 characters |
| `cost_price` | Decimal | Yes | > 0, max 2 decimal places |
| `selling_price` | Decimal | Yes | > 0, max 2 decimal places |
| `min_stock_level` | Integer | Yes | >= 0 |
| `max_stock_level` | Integer | Yes | > min_stock_level |
| `reorder_point` | Integer | No | >= 0, defaults to min_stock_level |
| `unit_of_measure` | String | Yes | e.g., "units", "kg", "liters" |
| `shelf_life_days` | Integer | No | > 0, nullable for non-perishable items |
| `barcode` | String | No | Unique if provided |
| `status` | Enum | Yes | `active`, `discontinued`, `draft` |
| `supplier_id` | FK | No | Must reference an existing supplier |

**Validation Rules:**
- `selling_price` should be >= `cost_price` (warning if not, but allow override)
- `sku` must be unique; return HTTP 409 Conflict if duplicate
- `barcode` must be unique if provided

**Response:** Return the created product with a server-generated `product_id` and `created_at` timestamp.

---

#### FR-PM-002 — Retrieve Product
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to retrieve a single product by `product_id`. The response shall include all product attributes and the associated supplier name (if linked).

---

#### FR-PM-003 — List Products
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to retrieve a paginated list of products.

**Pagination:** Offset-based. Default page size = 20. Maximum page size = 100.

**Filtering:** The system shall support filtering by:
- `category` (exact match)
- `brand` (exact match)
- `status` (exact match)
- `supplier_id` (exact match)
- `name` (partial match, case-insensitive)
- `sku` (partial match)
- `price_min` / `price_max` (range filter on selling_price)

**Sorting:** The system shall support sorting by `name`, `sku`, `selling_price`, `cost_price`, `created_at`. Default: `created_at DESC`.

**Response:** Return the list of products, total count, current page, page size, and total pages.

---

#### FR-PM-004 — Update Product
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to update an existing product by `product_id`. Partial updates shall be supported (PATCH semantics). All validation rules from FR-PM-001 apply to updated fields.

The system shall track `updated_at` timestamp and the user who made the update.

---

#### FR-PM-005 — Delete Product (Soft Delete)
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to soft-delete a product by setting its status to `discontinued`. The product shall not be permanently removed from the database.

**Constraint:** A product with active inventory (quantity > 0 in any warehouse) shall not be deletable. The system shall return HTTP 409 Conflict with a descriptive message.

---

#### FR-PM-006 — Product Search
**Priority:** P1  
**Stage:** 3  
The system shall support full-text search across product `name`, `sku`, `brand`, `category`, and `description` fields. Search shall return results ranked by relevance.

---

#### FR-PM-007 — Product History
**Priority:** P1  
**Stage:** 3  
The system shall maintain an audit log of all changes to a product record. Each log entry shall include the field changed, previous value, new value, user who made the change, and timestamp.

---

### 3.2 Inventory Management

**Business Context:** Inventory is the junction between products and warehouses. Every unit of every product is tracked in a specific warehouse with batch-level granularity. This module handles stock levels, movements, and the real-time state of goods.

---

#### FR-IM-001 — Create Inventory Record
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to create an inventory record linking a product to a warehouse.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `product_id` | FK | Yes | Must reference existing product |
| `warehouse_id` | FK | Yes | Must reference existing warehouse |
| `quantity` | Integer | Yes | >= 0 |
| `reserved_quantity` | Integer | No | >= 0, default 0, <= quantity |
| `batch_number` | String | No | Alphanumeric, for batch tracking |
| `expiry_date` | Date | No | Must be in the future if provided |
| `unit_cost` | Decimal | No | > 0, for FIFO/LIFO valuation |

**Derived Fields (computed by system):**
- `available_quantity` = `quantity` - `reserved_quantity`

**Constraint:** The combination of `product_id` + `warehouse_id` + `batch_number` must be unique. If a record already exists, the system shall return HTTP 409 Conflict and suggest using the stock adjustment endpoint instead.

---

#### FR-IM-002 — Retrieve Inventory
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to retrieve the inventory of a specific product across all warehouses, or all products in a specific warehouse.

**Response shall include:**
- Product details (name, SKU, category)
- Warehouse details (name, location)
- Quantity, reserved quantity, available quantity
- Batch number and expiry date (if applicable)
- Last updated timestamp

---

#### FR-IM-003 — List Inventory
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to retrieve a paginated list of all inventory records.

**Filtering:**
- `warehouse_id`
- `product_id`
- `category` (of the product)
- `status` — derived filter:
  - `low_stock`: available_quantity <= product.min_stock_level
  - `overstock`: available_quantity >= product.max_stock_level
  - `out_of_stock`: available_quantity = 0
  - `expiring_soon`: expiry_date within 30 days
  - `expired`: expiry_date < today

**Sorting:** By `quantity`, `available_quantity`, `expiry_date`, `updated_at`.

---

#### FR-IM-004 — Stock Adjustment
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to adjust inventory quantities. Adjustments shall include a mandatory `reason` field.

| Adjustment Type | Description |
|---|---|
| `received` | New stock received from supplier |
| `sold` | Stock sold to customer |
| `damaged` | Stock damaged and removed |
| `returned` | Stock returned by customer |
| `transferred_in` | Stock received from another warehouse |
| `transferred_out` | Stock sent to another warehouse |
| `correction` | Manual correction (audit adjustment) |
| `expired` | Expired stock removed |

**Validation:**
- Negative adjustments shall not reduce quantity below 0
- Every adjustment shall be logged in the inventory movement history (FR-IM-005)

---

#### FR-IM-005 — Inventory Movement History
**Priority:** P0  
**Stage:** 1  
The system shall maintain a complete, immutable history of all inventory changes. Each movement record shall include:

| Field | Description |
|---|---|
| `movement_id` | Unique identifier |
| `inventory_id` | Reference to inventory record |
| `product_id` | Product involved |
| `warehouse_id` | Warehouse involved |
| `movement_type` | Type from FR-IM-004 |
| `quantity_change` | Positive or negative integer |
| `quantity_before` | Stock level before the change |
| `quantity_after` | Stock level after the change |
| `reason` | Explanation of the change |
| `reference_id` | Optional link to sale, PO, or transfer |
| `performed_by` | User who made the change |
| `timestamp` | When the change occurred |

**Constraint:** Movement records shall never be modified or deleted. This is the audit trail.

---

#### FR-IM-006 — Low Stock Alert Trigger
**Priority:** P1  
**Stage:** 2  
When a stock adjustment causes `available_quantity` to fall at or below the product's `min_stock_level`, the system shall:
1. Flag the inventory record as `low_stock`
2. Create an alert record (see FR-NF-001)
3. Include the product in the next recommendation generation cycle

---

#### FR-IM-007 — Expiry Tracking
**Priority:** P1  
**Stage:** 3  
The system shall automatically identify inventory batches approaching expiry and flag them at configurable intervals:
- **Red alert:** Expiring within 7 days
- **Orange alert:** Expiring within 30 days
- **Yellow alert:** Expiring within 90 days

Expired inventory (expiry_date < today) shall be automatically flagged as `expired` and excluded from `available_quantity` calculations.

---

#### FR-IM-008 — Dead Stock Detection
**Priority:** P2  
**Stage:** 4  
The system shall identify dead inventory — products with zero or negligible sales activity over a configurable period (default: 90 days).

**Detection criteria:**
- No sales recorded for the product in the specified warehouse within the last N days
- Inventory quantity > 0

**Output:** Dead stock records shall include the product, warehouse, quantity, estimated holding cost, and number of days since last sale.

---

#### FR-IM-009 — Inventory Valuation
**Priority:** P2  
**Stage:** 4  
The system shall calculate inventory valuation using the **Weighted Average Cost** method.

- `inventory_value` = `quantity` × `weighted_average_unit_cost`
- Aggregated by warehouse, category, and total

This data feeds the Finance Manager's dashboard.

---

### 3.3 Warehouse Management

**Business Context:** Warehouses are the physical locations where inventory is stored. Managing warehouse capacity, utilization, and inter-warehouse transfers is essential for operational efficiency.

---

#### FR-WH-001 — Create Warehouse
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to create a warehouse.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | String | Yes | 1–255 characters, unique |
| `location` | String | Yes | City, state, or address |
| `capacity` | Integer | Yes | > 0 (in standard storage units) |
| `warehouse_type` | Enum | Yes | `main`, `regional`, `distribution_center`, `cold_storage` |
| `manager_name` | String | No | Name of the warehouse manager |
| `contact_email` | String | No | Valid email format |
| `contact_phone` | String | No | Valid phone format |
| `status` | Enum | Yes | `active`, `inactive`, `maintenance` |

---

#### FR-WH-002 — Retrieve Warehouse
**Priority:** P0  
**Stage:** 1  
The system shall return warehouse details along with computed utilization metrics:
- `current_utilization` — total quantity of all products stored
- `utilization_percentage` — (current_utilization / capacity) × 100
- `available_capacity` — capacity - current_utilization
- `product_count` — number of distinct products stored
- `total_inventory_value` — sum of inventory value in the warehouse

---

#### FR-WH-003 — List Warehouses
**Priority:** P0  
**Stage:** 1  
The system shall return a paginated list of all warehouses with filtering by `status`, `warehouse_type`, and `location`. Include utilization summary for each warehouse.

---

#### FR-WH-004 — Update Warehouse
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to update warehouse attributes. Reducing `capacity` below `current_utilization` shall return HTTP 409 Conflict.

---

#### FR-WH-005 — Inter-Warehouse Transfer
**Priority:** P1  
**Stage:** 3  
The system shall allow authorized users to initiate a stock transfer between warehouses.

**Transfer flow:**
1. User creates a transfer request: source warehouse, destination warehouse, product, quantity
2. System validates source warehouse has sufficient available quantity
3. System creates a transfer record with status `pending`
4. Upon confirmation, system:
   - Decrements source warehouse inventory (movement type: `transferred_out`)
   - Increments destination warehouse inventory (movement type: `transferred_in`)
   - Updates transfer status to `completed`

**Transfer record fields:**
| Field | Description |
|---|---|
| `transfer_id` | Unique identifier |
| `source_warehouse_id` | Origin warehouse |
| `destination_warehouse_id` | Target warehouse |
| `product_id` | Product being transferred |
| `quantity` | Units transferred |
| `status` | `pending`, `in_transit`, `completed`, `cancelled` |
| `initiated_by` | User who created the request |
| `initiated_at` | Timestamp |
| `completed_at` | Timestamp (nullable) |

---

#### FR-WH-006 — Warehouse Utilization Report
**Priority:** P1  
**Stage:** 4  
The system shall generate a warehouse utilization report showing:
- Capacity vs. current utilization for each warehouse
- Utilization trend over time (daily/weekly snapshots)
- Top 10 products by space consumed in each warehouse
- Warehouses exceeding 85% utilization (flagged as at-risk)

---

### 3.4 Supplier Management

**Business Context:** Suppliers are the upstream partners who provide products. Tracking their performance objectively — not by gut feeling — enables better procurement decisions. This module lays the foundation for the Supplier Intelligence feature.

---

#### FR-SP-001 — Create Supplier
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to create a supplier record.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `company_name` | String | Yes | 1–255 characters, unique |
| `contact_person` | String | No | 1–255 characters |
| `email` | String | Yes | Valid email format |
| `phone` | String | No | Valid phone format |
| `address` | String | No | Max 500 characters |
| `average_lead_time_days` | Integer | No | > 0 |
| `payment_terms` | String | No | e.g., "Net 30", "Net 60" |
| `status` | Enum | Yes | `active`, `inactive`, `blacklisted` |

---

#### FR-SP-002 — Retrieve Supplier
**Priority:** P0  
**Stage:** 1  
The system shall return supplier details. In Stage 4+, the response shall also include computed performance metrics:
- `on_time_delivery_rate` — percentage of orders delivered on or before expected date
- `quality_rating` — average quality score across deliveries
- `total_orders` — lifetime purchase orders
- `average_actual_lead_time` — computed from historical deliveries
- `reliability_score` — composite score (calculated in FR-SP-005)

---

#### FR-SP-003 — List Suppliers
**Priority:** P0  
**Stage:** 1  
Paginated list with filtering by `status` and sorting by `company_name`, `reliability_score`, `on_time_delivery_rate`.

---

#### FR-SP-004 — Update Supplier
**Priority:** P0  
**Stage:** 1  
Standard update with audit trail. Changing status to `blacklisted` shall trigger a notification (FR-NF-003).

---

#### FR-SP-005 — Supplier Scoring
**Priority:** P2  
**Stage:** 7  
The system shall compute a `reliability_score` for each supplier using the following weighted formula:

```
reliability_score = (
    0.40 × on_time_delivery_rate +
    0.25 × quality_rating +
    0.20 × order_accuracy_rate +
    0.15 × consistency_score
)
```

Where:
- `on_time_delivery_rate` = orders delivered on time / total orders
- `quality_rating` = average of quality scores (1–5 scale, normalized to 0–1)
- `order_accuracy_rate` = orders with correct quantity / total orders
- `consistency_score` = 1 - (standard deviation of delivery delay / mean delivery delay), clamped to [0, 1]

The score shall be recalculated daily or when a new purchase order is marked as delivered.

---

#### FR-SP-006 — Supplier Comparison
**Priority:** P2  
**Stage:** 7  
The system shall allow users to compare up to 5 suppliers side-by-side across all performance metrics. The comparison shall highlight the best and worst performer in each category.

---

### 3.5 Purchase Order Management

**Business Context:** Purchase orders are the formal mechanism for ordering products from suppliers. They are the primary source of data for supplier performance evaluation and form the link between supplier management and inventory management.

---

#### FR-PO-001 — Create Purchase Order
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to create a purchase order.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `supplier_id` | FK | Yes | Must reference existing active supplier |
| `warehouse_id` | FK | Yes | Destination warehouse |
| `order_date` | Date | Yes | Defaults to today |
| `expected_delivery_date` | Date | Yes | Must be after order_date |
| `status` | Enum | Yes | `draft`, `submitted`, `confirmed`, `shipped`, `delivered`, `cancelled` |
| `notes` | String | No | Max 1000 characters |

**Line items (at least one required):**
| Field | Type | Required | Constraints |
|---|---|---|---|
| `product_id` | FK | Yes | Must reference existing product |
| `quantity` | Integer | Yes | > 0 |
| `unit_price` | Decimal | Yes | > 0 |

**Derived fields:**
- `total_amount` = sum of (quantity × unit_price) for all line items
- `line_item_count` = number of line items

---

#### FR-PO-002 — Retrieve Purchase Order
**Priority:** P0  
**Stage:** 1  
Return the PO with all line items, supplier details, and delivery status information.

---

#### FR-PO-003 — List Purchase Orders
**Priority:** P0  
**Stage:** 1  
Paginated list with filtering by `supplier_id`, `warehouse_id`, `status`, `order_date` range, `expected_delivery_date` range.

---

#### FR-PO-004 — Update Purchase Order Status
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to advance the PO through its lifecycle:

```
draft → submitted → confirmed → shipped → delivered
                                    ↘ cancelled
```

**On transition to `delivered`:**
1. Record `actual_delivery_date`
2. Calculate `delivery_delay_days` = `actual_delivery_date` - `expected_delivery_date` (can be negative if early)
3. Automatically create inventory adjustments (type: `received`) for each line item
4. Update supplier performance metrics

**On transition to `cancelled`:**
- Record cancellation reason (mandatory)
- No inventory adjustments

---

#### FR-PO-005 — Overdue PO Detection
**Priority:** P1  
**Stage:** 3  
The system shall automatically flag purchase orders where:
- Status is `submitted`, `confirmed`, or `shipped`
- `expected_delivery_date` < today

Overdue POs shall generate alerts (FR-NF-002).

---

### 3.6 Sales Management

**Business Context:** Sales data is the heartbeat of the system. It drives demand forecasting, inventory turnover analysis, ABC classification, and revenue analytics. Without accurate sales data, the AI Decision Support Engine has no signal.

---

#### FR-SA-001 — Record Sale
**Priority:** P0  
**Stage:** 1  
The system shall allow authorized users to record a sale.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `product_id` | FK | Yes | Must reference existing product |
| `warehouse_id` | FK | Yes | Must reference existing warehouse |
| `customer_id` | FK | No | Reference to customer, if known |
| `quantity` | Integer | Yes | > 0, <= available_quantity |
| `unit_price` | Decimal | Yes | > 0 |
| `discount_percentage` | Decimal | No | 0–100, default 0 |
| `sale_date` | DateTime | Yes | Defaults to now |

**Derived fields:**
- `subtotal` = quantity × unit_price
- `discount_amount` = subtotal × (discount_percentage / 100)
- `revenue` = subtotal - discount_amount
- `profit` = revenue - (quantity × product.cost_price)

**Side effects:**
- Automatically create inventory adjustment (type: `sold`) reducing stock
- If resulting `available_quantity` <= `min_stock_level`, trigger low stock alert (FR-IM-006)

---

#### FR-SA-002 — Retrieve Sale
**Priority:** P0  
**Stage:** 1  
Return sale record with product details, warehouse details, and customer details (if available).

---

#### FR-SA-003 — List Sales
**Priority:** P0  
**Stage:** 1  
Paginated list with filtering by `product_id`, `warehouse_id`, `customer_id`, `sale_date` range. Sorting by `sale_date`, `revenue`, `quantity`.

---

#### FR-SA-004 — Sales Summary
**Priority:** P1  
**Stage:** 4  
The system shall provide aggregated sales summaries:
- **By product:** total quantity sold, total revenue, total profit, average selling price
- **By warehouse:** total sales count, total revenue, top-selling products
- **By time period:** daily, weekly, monthly, quarterly aggregations
- **By category:** revenue and quantity per product category

---

### 3.7 Customer Management

**Business Context:** While OptiStock is not a CRM, basic customer tracking enables sales analysis by customer segment, lifetime value computation, and demand pattern analysis across customer types.

---

#### FR-CU-001 — Create Customer
**Priority:** P1  
**Stage:** 1  
The system shall allow authorized users to create a customer record.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | String | Yes | 1–255 characters |
| `email` | String | No | Valid email, unique if provided |
| `phone` | String | No | Valid phone format |
| `region` | String | Yes | Geographic region |
| `customer_type` | Enum | Yes | `retail`, `wholesale`, `distributor`, `internal` |
| `status` | Enum | Yes | `active`, `inactive` |

---

#### FR-CU-002 — Retrieve Customer
**Priority:** P1  
**Stage:** 1  
Return customer details. In Stage 4+, include:
- `total_orders` — lifetime count of sales
- `lifetime_value` — total revenue from this customer
- `average_order_value` — lifetime_value / total_orders
- `last_order_date` — most recent sale date

---

#### FR-CU-003 — List Customers
**Priority:** P1  
**Stage:** 1  
Paginated list with filtering by `customer_type`, `region`, `status`.

---

### 3.8 Analytics and Reporting

**Business Context:** This module converts raw operational data into business insights. It powers the dashboards that each user persona relies on for decision-making. Analytics requirements are defined as specific KPIs with precise calculation logic.

---

#### FR-AN-001 — Inventory Turnover Ratio
**Priority:** P1  
**Stage:** 4  
The system shall calculate inventory turnover ratio:

```
Inventory Turnover = Cost of Goods Sold (COGS) / Average Inventory Value
```

Where:
- COGS = sum of (quantity_sold × cost_price) for the period
- Average Inventory Value = (beginning inventory value + ending inventory value) / 2

Available per product, per category, per warehouse, and system-wide.
A higher ratio indicates efficient inventory management.

---

#### FR-AN-002 — ABC Classification
**Priority:** P1  
**Stage:** 4  
The system shall classify products using ABC analysis based on revenue contribution:

| Class | Criteria | Typical Range |
|---|---|---|
| **A** | Top products contributing to ~80% of total revenue | ~20% of products |
| **B** | Next set contributing to ~15% of total revenue | ~30% of products |
| **C** | Remaining products contributing to ~5% of total revenue | ~50% of products |

The classification shall be recalculated weekly or on-demand.

---

#### FR-AN-003 — Revenue Dashboard API
**Priority:** P1  
**Stage:** 4  
The system shall provide a dashboard API returning:
- Total revenue (today, this week, this month, this quarter, this year)
- Revenue trend (daily data points for the selected period)
- Revenue by category (pie/bar chart data)
- Revenue by warehouse
- Top 10 products by revenue
- Bottom 10 products by revenue
- Gross profit margin = (revenue - COGS) / revenue × 100

---

#### FR-AN-004 — Inventory Health Dashboard API
**Priority:** P1  
**Stage:** 4  
The system shall provide:
- Total inventory value across all warehouses
- Inventory value by warehouse
- Count and value of low stock items
- Count and value of overstock items
- Count and value of dead stock items
- Count and value of expiring items (30/60/90 days)
- Inventory accuracy percentage (if reconciliation data exists)

---

#### FR-AN-005 — Warehouse Comparison Dashboard API
**Priority:** P1  
**Stage:** 4  
The system shall provide side-by-side comparison of all warehouses:
- Utilization percentage
- Total inventory value
- Number of products
- Inbound transfers (last 30 days)
- Outbound transfers (last 30 days)
- Top 5 products by quantity in each warehouse

---

#### FR-AN-006 — Supplier Performance Dashboard API
**Priority:** P2  
**Stage:** 7  
The system shall provide:
- Supplier ranking by reliability score
- Average delivery delay per supplier
- On-time delivery trend (monthly)
- Open purchase orders by supplier
- Supplier cost comparison for shared products

---

#### FR-AN-007 — Executive Summary API
**Priority:** P2  
**Stage:** 8  
The system shall provide a single-endpoint executive summary:
- Total revenue (current period vs. previous period, with % change)
- Total inventory value
- Active alerts count (by severity)
- Top 3 recommendations (highest priority)
- Demand forecast summary (next 30 days)
- Capital locked in dead stock
- Warehouse utilization heatmap data

---

### 3.9 ETL and Data Import

**Business Context:** Real businesses don't type inventory data one record at a time. They export from ERPs, receive supplier spreadsheets, and need to load historical data. The ETL layer makes OptiStock useful in a real-world context.

---

#### FR-ET-001 — CSV Import
**Priority:** P1  
**Stage:** 5  
The system shall accept CSV file uploads for bulk data import.

**Supported entities:** Products, Inventory, Sales, Suppliers, Customers, Purchase Orders.

**Process:**
1. User uploads a CSV file via API (multipart/form-data)
2. System validates the file (size <= 50MB, valid CSV format)
3. System parses headers and maps columns to entity fields
4. System validates each row:
   - Required fields present
   - Data types correct
   - Foreign key references valid
   - Business rules satisfied
5. System returns a validation report:
   - Total rows
   - Valid rows
   - Invalid rows (with row number and error description)
6. User confirms import
7. System inserts valid rows and skips invalid rows
8. System returns an import summary

---

#### FR-ET-002 — Excel Import
**Priority:** P1  
**Stage:** 5  
Same as FR-ET-001, but for `.xlsx` files. The system shall support reading the first sheet by default, with an option to specify the sheet name.

---

#### FR-ET-003 — Data Validation Pipeline
**Priority:** P1  
**Stage:** 5  
The system shall apply the following validation steps to all imported data:

| Step | Description |
|---|---|
| Schema validation | Column names match expected schema |
| Type validation | Values match expected data types |
| Null check | Required fields are not null or empty |
| Range check | Numeric values within acceptable ranges |
| Uniqueness check | SKU, barcode, email uniqueness |
| Referential integrity | Foreign keys reference existing records |
| Duplicate detection | Detect duplicate rows within the import file |
| Business rule validation | e.g., selling_price >= cost_price |

---

#### FR-ET-004 — Scheduled ETL Pipeline
**Priority:** P1  
**Stage:** 6  
The system shall support scheduled data processing pipelines (initially via Python scripts, later via Apache Airflow).

**Pipeline capabilities:**
- Run on a configurable schedule (cron expression)
- Process data from a configured source directory or API endpoint
- Apply validation, cleaning, and transformation rules
- Load processed data into the database
- Log pipeline execution: start time, end time, records processed, records failed, errors
- Retry failed pipeline runs (configurable retry count, default: 3)

---

#### FR-ET-005 — Data Export
**Priority:** P1  
**Stage:** 5  
The system shall allow users to export data as CSV for: Products, Inventory, Sales, Suppliers, Purchase Orders.

**Options:**
- Filter before export (same filters as list endpoints)
- Select columns to include
- Maximum export size: 500,000 rows

---

### 3.10 Demand Forecasting

**Business Context:** Demand forecasting is the predictive engine that transforms OptiStock from a record-keeping system into a forward-looking intelligence platform. Accurate forecasts feed directly into the Recommendation Engine.

---

#### FR-FC-001 — Generate Demand Forecast
**Priority:** P2  
**Stage:** 7  
The system shall generate demand forecasts at the product level.

**Input:**
- Historical sales data (minimum 12 weeks of data required)
- Product ID
- Forecast horizon (default: 4 weeks)

**Output per forecast period (week):**
| Field | Description |
|---|---|
| `product_id` | Product being forecasted |
| `period_start` | Start date of the forecast period |
| `period_end` | End date of the forecast period |
| `predicted_demand` | Predicted quantity to be sold |
| `lower_bound` | Lower 80% confidence interval |
| `upper_bound` | Upper 80% confidence interval |
| `confidence_score` | 0.0 to 1.0, model's confidence in this prediction |
| `model_used` | Algorithm that generated this forecast |
| `generated_at` | Timestamp of forecast generation |

**Algorithms (in order of implementation):**
1. Moving Average (baseline)
2. Linear Regression
3. Random Forest
4. XGBoost
5. Prophet (if seasonality detected)

The system shall automatically select the best-performing model based on backtesting (MAPE on held-out data).

---

#### FR-FC-002 — Forecast Accuracy Tracking
**Priority:** P2  
**Stage:** 7  
The system shall track forecast accuracy by comparing predictions to actual sales after the forecast period elapses.

**Metrics computed:**
- MAPE (Mean Absolute Percentage Error)
- RMSE (Root Mean Squared Error)
- Bias (average over-prediction or under-prediction)

**Target:** MAPE < 20% for A-class products (top revenue contributors).

---

#### FR-FC-003 — Retrieve Forecasts
**Priority:** P2  
**Stage:** 7  
The system shall allow users to retrieve demand forecasts:
- By product (all future periods)
- By warehouse (all products in that warehouse)
- By date range
- Include actual vs. predicted comparison for past periods

---

#### FR-FC-004 — Batch Forecast Generation
**Priority:** P2  
**Stage:** 7  
The system shall support batch forecast generation for all active products (or a subset by category/warehouse) via a single API call or scheduled pipeline.

---

### 3.11 Inventory Optimization

**Business Context:** This module uses mathematical formulas and business logic to calculate optimal inventory levels. It bridges the gap between raw data and actionable inventory decisions.

---

#### FR-OP-001 — Economic Order Quantity (EOQ)
**Priority:** P2  
**Stage:** 8  
The system shall calculate EOQ for each product:

```
EOQ = sqrt((2 × D × S) / H)
```

Where:
- D = Annual demand (from sales data or forecast)
- S = Ordering cost per order (configurable, default from supplier)
- H = Holding cost per unit per year (configurable, default: 20% of unit cost)

---

#### FR-OP-002 — Reorder Point (ROP)
**Priority:** P2  
**Stage:** 8  
The system shall calculate the reorder point:

```
ROP = (Average Daily Demand × Lead Time in Days) + Safety Stock
```

Where:
- Average Daily Demand = total sales over last 90 days / 90
- Lead Time = supplier's `average_lead_time_days`
- Safety Stock = FR-OP-003

---

#### FR-OP-003 — Safety Stock
**Priority:** P2  
**Stage:** 8  
The system shall calculate safety stock:

```
Safety Stock = Z × σ_d × sqrt(L)
```

Where:
- Z = service level factor (default: 1.65 for 95% service level)
- σ_d = standard deviation of daily demand
- L = lead time in days

---

#### FR-OP-004 — Transfer Optimization
**Priority:** P2  
**Stage:** 8  
The system shall identify transfer opportunities between warehouses:
- Find products overstocked in one warehouse and low/out of stock in another
- Calculate the recommended transfer quantity
- Rank transfer opportunities by potential impact (revenue at risk × probability of stockout)

---

### 3.12 Recommendation Engine

**Business Context:** This is the hero feature — the AI Decision Support Engine. It synthesizes data from forecasting, optimization, supplier scoring, and inventory health to generate specific, actionable, prioritized recommendations that tell businesses what to do next.

---

#### FR-RC-001 — Generate Recommendations
**Priority:** P2  
**Stage:** 8  
The system shall generate recommendations of the following types:

| Type | Trigger | Example |
|---|---|---|
| `reorder` | Available stock <= ROP or predicted demand > available stock | "Order 900 units of Product X from Supplier A within 3 days" |
| `transfer` | Overstock in Warehouse A + low stock in Warehouse B for same product | "Transfer 600 units from Warehouse A to Warehouse B" |
| `discontinue` | Dead stock for 180+ days with no forecast demand | "Consider discontinuing Product Y — zero sales in 6 months" |
| `discount` | Slow-moving stock + high inventory level | "Apply 20% discount to Product Z to accelerate movement" |
| `switch_supplier` | Supplier reliability score < 0.5 or delivery delay rate > 40% | "Replace Supplier C — 45% delivery delay rate. Alternatives: Supplier D (score: 0.92)" |
| `reduce_order` | Demand forecast shows declining trend + current overstock | "Reduce next order for Product W from 500 to 200 units" |
| `expiry_action` | Inventory expiring within 30 days | "300 units of Product V expire in 15 days — consider discounting or transferring" |

---

#### FR-RC-002 — Recommendation Structure
**Priority:** P2  
**Stage:** 8  
Each recommendation shall include:

**Core Fields:**

| Field | Description |
|---|---|
| `recommendation_id` | Unique identifier |
| `type` | From the types in FR-RC-001 |
| `priority` | `critical`, `high`, `medium`, `low` |
| `title` | Short, human-readable summary |
| `description` | Detailed explanation |
| `affected_product_id` | Product involved |
| `affected_warehouse_id` | Warehouse involved (if applicable) |
| `affected_supplier_id` | Supplier involved (if applicable) |
| `recommended_action` | Specific action to take |
| `recommended_quantity` | Quantity involved (if applicable) |
| `estimated_impact` | Estimated cost savings or revenue impact |
| `confidence` | 0.0 to 1.0 |
| `status` | `pending`, `accepted`, `rejected`, `implemented` |
| `generated_at` | Timestamp |
| `expires_at` | When the recommendation becomes stale |

**Explainability Fields (required for every recommendation):**

These fields ensure that every recommendation is transparent, auditable, and trustworthy. A recommendation without reasoning is just noise.

| Field | Type | Description |
|---|---|---|
| `reasoning` | Object | Structured explanation of why the recommendation was generated |
| `reasoning.summary` | String | One-sentence human-readable explanation. Example: *"Predicted demand (980 units) exceeds available stock (250 units) by 730 units within the next 14 days."* |
| `reasoning.trigger_rule` | String | The business rule or condition that triggered this recommendation. Example: `predicted_demand > available_stock + incoming_orders` |
| `reasoning.evidence` | Array | List of data points that support the recommendation |
| `reasoning.evidence[].metric` | String | Name of the metric. Example: `current_stock`, `predicted_demand_14d`, `supplier_lead_time` |
| `reasoning.evidence[].value` | Any | Current value of the metric |
| `reasoning.evidence[].threshold` | Any | The threshold or comparison value (if applicable) |
| `reasoning.evidence[].source` | String | Where this data came from: `inventory`, `forecast`, `supplier_history`, `sales_history`, `optimization` |
| `reasoning.alternatives_considered` | Array | Other options the engine evaluated and why they were not recommended |
| `reasoning.alternatives_considered[].action` | String | The alternative action. Example: *"Order from Supplier B instead"* |
| `reasoning.alternatives_considered[].reason_rejected` | String | Why this was not the top recommendation. Example: *"Supplier B has 12-day lead time vs. Supplier A's 5-day lead time"* |
| `reasoning.confidence_explanation` | String | Why the confidence score is what it is. Example: *"High confidence — based on 48 weeks of sales history with stable demand pattern"* |
| `reasoning.risk_if_ignored` | String | What happens if this recommendation is not acted upon. Example: *"Estimated stockout in 8 days. Projected revenue loss: $12,400."* |

**Example — Complete Recommendation with Explainability:**

```json
{
  "recommendation_id": "rec_20260701_001",
  "type": "reorder",
  "priority": "critical",
  "title": "Urgent: Reorder Product X from Supplier A",
  "description": "Order 900 units of Product X (SKU: ELEC-2847) from Supplier A within 3 days to prevent stockout.",
  "affected_product_id": "prod_2847",
  "affected_warehouse_id": "wh_001",
  "affected_supplier_id": "sup_014",
  "recommended_action": "Create purchase order for 900 units",
  "recommended_quantity": 900,
  "estimated_impact": {
    "revenue_at_risk": 42000.00,
    "cost_of_action": 18900.00,
    "net_benefit": 23100.00
  },
  "confidence": 0.89,
  "status": "pending",
  "reasoning": {
    "summary": "Predicted demand (980 units) over the next 14 days exceeds available stock (250 units). Supplier A has the shortest lead time and highest reliability.",
    "trigger_rule": "predicted_demand_14d > available_stock + incoming_po_quantity",
    "evidence": [
      { "metric": "current_available_stock", "value": 250, "threshold": null, "source": "inventory" },
      { "metric": "predicted_demand_14d", "value": 980, "threshold": null, "source": "forecast" },
      { "metric": "incoming_po_quantity", "value": 0, "threshold": null, "source": "purchase_orders" },
      { "metric": "supplier_a_lead_time_days", "value": 5, "threshold": null, "source": "supplier_history" },
      { "metric": "supplier_a_reliability_score", "value": 0.94, "threshold": 0.5, "source": "supplier_history" },
      { "metric": "reorder_point", "value": 320, "threshold": null, "source": "optimization" },
      { "metric": "eoq", "value": 900, "threshold": null, "source": "optimization" }
    ],
    "alternatives_considered": [
      {
        "action": "Order from Supplier B (SupTech Ltd)",
        "reason_rejected": "Lead time is 12 days vs. 5 days. Would not arrive before projected stockout."
      },
      {
        "action": "Transfer 200 units from Warehouse B",
        "reason_rejected": "Warehouse B only has 180 units — would leave both warehouses at risk."
      }
    ],
    "confidence_explanation": "High confidence — prediction based on 52 weeks of sales history. Product shows stable demand with low variance (CV = 0.12).",
    "risk_if_ignored": "Projected stockout in 4 days. Based on current sales velocity (68 units/day), estimated revenue loss: $42,000 over 9 days until next possible delivery."
  }
}
```

---

#### FR-RC-003 — Retrieve Recommendations
**Priority:** P2  
**Stage:** 8  
The system shall allow users to retrieve recommendations with filtering by:
- `type`
- `priority`
- `status`
- `product_id`
- `warehouse_id`

Default: return `pending` recommendations sorted by `priority` (critical first) then by `estimated_impact` (highest first).

---

#### FR-RC-004 — Act on Recommendation
**Priority:** P2  
**Stage:** 8  
The system shall allow users to:
- **Accept** a recommendation — status changes to `accepted`, and the system pre-fills the corresponding action (e.g., creates a draft purchase order for a reorder recommendation)
- **Reject** a recommendation — status changes to `rejected`, user provides a reason
- **Dismiss** a recommendation — status changes to `dismissed` (no reason required)

The system shall track acceptance rate as a metric for recommendation quality.

---

#### FR-RC-005 — Scheduled Recommendation Generation
**Priority:** P2  
**Stage:** 8  
The system shall run the recommendation generation engine on a configurable schedule (default: daily at 2:00 AM).

The engine shall:
1. Analyze current inventory levels across all warehouses
2. Compare against demand forecasts
3. Evaluate supplier performance
4. Apply optimization calculations (EOQ, ROP, Safety Stock)
5. Apply business rules
6. Generate new recommendations
7. Expire stale recommendations (older than 7 days, still `pending`)

---

### 3.13 Authentication and Authorization

**Business Context:** Every enterprise application must control who can access what. OptiStock handles sensitive business data (pricing, supplier contracts, financial metrics). Unauthorized access could cause competitive damage or data corruption.

---

#### FR-AU-001 — User Registration
**Priority:** P0  
**Stage:** 2  
The system shall allow new users to register with:

| Field | Type | Required | Constraints |
|---|---|---|---|
| `email` | String | Yes | Valid email, unique |
| `password` | String | Yes | Minimum 8 characters, at least 1 uppercase, 1 lowercase, 1 digit, 1 special character |
| `full_name` | String | Yes | 1–255 characters |
| `role` | Enum | Yes | Must be a valid role (see Section 2.2) |

**Password storage:** Bcrypt hash with cost factor >= 12. Plaintext passwords shall never be stored or logged.

---

#### FR-AU-002 — User Login
**Priority:** P0  
**Stage:** 2  
The system shall authenticate users via email and password.

**On success:** Return:
- `access_token` (JWT, expires in 30 minutes)
- `refresh_token` (opaque token, expires in 7 days)
- User profile (id, email, name, role)

**On failure:** Return HTTP 401 with a generic message ("Invalid credentials"). Do not reveal whether the email exists.

**Rate limiting:** Maximum 5 failed login attempts per email per 15-minute window. After exceeding, return HTTP 429.

---

#### FR-AU-003 — Token Refresh
**Priority:** P0  
**Stage:** 2  
The system shall allow users to obtain a new access token using a valid refresh token, without re-entering credentials.

**Refresh token rotation:** Each refresh generates a new refresh token and invalidates the old one.

---

#### FR-AU-004 — JWT Structure
**Priority:** P0  
**Stage:** 2  
The JWT payload shall contain:

```json
{
  "sub": "user_id",
  "email": "user@example.com",
  "role": "warehouse_manager",
  "iat": 1234567890,
  "exp": 1234569690
}
```

The token shall be signed with HS256 (or RS256 in production) using a server-side secret.

---

#### FR-AU-005 — Role-Based Access Control (RBAC)
**Priority:** P0  
**Stage:** 2  
The system shall enforce permissions based on user role. The permission matrix:

| Endpoint Group | Admin | Warehouse Mgr | Procurement Mgr | Sales Analyst | Finance Mgr | Supply Chain Mgr | Executive |
|---|---|---|---|---|---|---|---|
| Products (CRUD) | Full | Read | Full | Read | Read | Read | Read |
| Inventory (CRUD) | Full | Full | Read | Read | Read | Read | Read |
| Warehouses (CRUD) | Full | Read + Update | Read | Read | Read | Read | Read |
| Transfers | Full | Create + Read | Read | — | — | Full (incl. Approve) | Read |
| Suppliers (CRUD) | Full | Read | Full | Read | Read | Read | Read |
| Purchase Orders | Full | Read | Full | Read | Read | Read | Read |
| Sales (CRUD) | Full | Read + Create | Read | Read + Create (no delete) | Read | Read | Read |
| Customers (CRUD) | Full | Read | Read | Read + Create + Update | Read | Read | Read |
| Analytics | Full | Warehouse scope | Supplier scope | Full | Full | Full | Full |
| Forecasts | Full | Read | Read | Read | Read | Read | Read |
| Recommendations | Full | Read + Act | Read + Act | Read | Read | Read + Act | Read |
| Reconciliation | Full | Full | — | — | Read | Read | Read |
| Users (CRUD) | Full | — | — | — | — | — | — |
| System Config | Full | — | — | — | — | — | — |

**RBAC Rationale for Key Decisions:**

| Decision | Reasoning |
|---|---|
| Procurement Mgr → Full Product CRUD | Procurement owns the product catalog — they negotiate with suppliers, set cost prices, and onboard new products |
| Sales Analyst → No Delete on Sales | Sales records are immutable business events. Deleting a sale corrupts revenue analytics, forecasting, and audit trails. Only Admin can void a sale. |
| Supply Chain Mgr → Full Transfer (incl. Approve) | Supply Chain owns cross-warehouse logistics. They need to approve, initiate, and complete transfers without waiting for Admin approval. |
| Warehouse Mgr → Create Transfer (not Approve) | Warehouse managers can request transfers for their warehouse, but cross-warehouse decisions require Supply Chain Manager approval. |

---

#### FR-AU-006 — Logout
**Priority:** P0  
**Stage:** 2  
The system shall invalidate the user's refresh token on logout. The access token remains valid until expiry (stateless JWT), but the refresh token shall be blacklisted.

---

#### FR-AU-007 — Password Change
**Priority:** P1  
**Stage:** 2  
The system shall allow authenticated users to change their password. Requires current password verification before accepting the new password.

---

### 3.14 Notifications and Alerts

**Business Context:** Alerts ensure that critical inventory events are not missed. A stockout that goes unnoticed for 3 days is far more costly than one that triggers an immediate notification.

---

#### FR-NF-001 — Low Stock Alert
**Priority:** P1  
**Stage:** 3  
The system shall generate an alert when inventory for a product in any warehouse falls at or below the product's `min_stock_level`.

**Alert payload:**
- Product name and SKU
- Warehouse name
- Current available quantity
- Minimum stock level
- Recommended action (link to reorder recommendation if available)

---

#### FR-NF-002 — Overdue Purchase Order Alert
**Priority:** P1  
**Stage:** 3  
The system shall generate an alert when a purchase order passes its `expected_delivery_date` without being marked as `delivered`.

---

#### FR-NF-003 — Supplier Performance Alert
**Priority:** P2  
**Stage:** 7  
The system shall generate an alert when a supplier's `reliability_score` drops below 0.5 or when their `on_time_delivery_rate` drops below 60%.

---

#### FR-NF-004 — Expiry Alert
**Priority:** P1  
**Stage:** 3  
The system shall generate alerts for inventory approaching expiry (7, 30, 90 day thresholds as defined in FR-IM-007).

---

#### FR-NF-005 — Warehouse Capacity Alert
**Priority:** P1  
**Stage:** 4  
The system shall generate an alert when warehouse utilization exceeds 85%.

---

#### FR-NF-006 — Alert Management API
**Priority:** P1  
**Stage:** 3  
The system shall provide APIs to:
- List all alerts (paginated, filterable by type, severity, status, date range)
- Retrieve a single alert
- Acknowledge an alert (changes status from `active` to `acknowledged`)
- Resolve an alert (changes status to `resolved`)
- Alert severities: `critical`, `warning`, `info`

---

#### FR-NF-007 — Email Notifications
**Priority:** P3  
**Stage:** 11  
The system shall send email notifications for `critical` alerts. Email delivery shall be asynchronous (via background task queue). Users shall be able to configure email notification preferences.

---

### 3.15 Administration

**Business Context:** Administration features enable the platform to be managed by non-developers. User management, system configuration, and audit logs are table-stakes for enterprise software.

---

#### FR-AD-001 — User Management
**Priority:** P0  
**Stage:** 2  
Admin users shall be able to:
- Create new users
- Update user roles
- Deactivate users (soft delete)
- View all users with their roles and last login timestamp
- Reset a user's password

---

#### FR-AD-002 — Audit Log
**Priority:** P1  
**Stage:** 3  
The system shall maintain an immutable audit log of all business-critical actions:

| Field | Description |
|---|---|
| `log_id` | Unique identifier |
| `user_id` | Who performed the action |
| `action` | What was done (e.g., `product.created`, `inventory.adjusted`, `user.login`) |
| `resource_type` | Entity type affected |
| `resource_id` | Entity ID affected |
| `details` | JSON object with relevant data (e.g., changed fields) |
| `ip_address` | Client IP address |
| `timestamp` | When the action occurred |

Audit logs shall never be modified or deleted.

---

#### FR-AD-003 — System Health Check
**Priority:** P1  
**Stage:** 3  
The system shall expose a `/health` endpoint that returns:

```json
{
  "status": "healthy",
  "timestamp": "2026-07-01T10:00:00Z",
  "checks": {
    "database": { "status": "up", "response_time_ms": 5 },
    "redis": { "status": "up", "response_time_ms": 2 },
    "disk_space": { "status": "ok", "free_gb": 45.2 }
  },
  "version": "1.0.0"
}
```

This endpoint shall be unauthenticated (for load balancer and monitoring tool access).

---

#### FR-AD-004 — System Configuration
**Priority:** P2  
**Stage:** 9  
The system shall support runtime-configurable settings:
- Default pagination size
- Alert thresholds (low stock, overstock, capacity)
- Forecast horizon (weeks)
- Safety stock service level (Z-score)
- Dead stock threshold (days)
- Expiry alert intervals (days)

Settings shall be stored in the database and cached in memory (or Redis). Changes shall take effect without application restart.

---

### 3.16 Inventory Reconciliation

**Business Context:** In every warehouse, the system's recorded inventory eventually drifts from reality. Products get damaged and not reported. Shipments are miscounted. Items are placed on wrong shelves. Returns are processed incorrectly. Without a formal reconciliation process, every downstream decision — purchasing, forecasting, fulfillment — is based on incorrect data. This is the #1 silent failure in inventory systems.

Reconciliation is the process of comparing **what the system says** against **what the warehouse physically has**, identifying discrepancies, and adjusting records to match reality.

---

#### FR-IR-001 — Create Reconciliation Session
**Priority:** P1  
**Stage:** 4  
The system shall allow authorized users to create a reconciliation session.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `warehouse_id` | FK | Yes | Must reference an active warehouse |
| `scope` | Enum | Yes | `full` (all products), `category` (specific category), `zone` (specific area), `sample` (random subset) |
| `scope_filter` | String | No | Category name, zone ID, or sample percentage depending on scope |
| `scheduled_date` | Date | Yes | The date the physical count will be performed |
| `assigned_to` | FK | No | User responsible for the count |
| `notes` | String | No | Max 1000 characters |
| `status` | Enum | Auto | `draft`, `in_progress`, `pending_review`, `approved`, `completed` |

**On creation:** The system shall generate a **count sheet** — a list of all products within the reconciliation scope, showing:
- Product ID, name, SKU
- System quantity (what the system currently records)
- Blank field for physical count (to be filled during counting)

The count sheet shall NOT show the system quantity to the person performing the count if the `blind_count` option is enabled. This prevents bias — the counter records what they actually see, not what they expect.

---

#### FR-IR-002 — Record Physical Count
**Priority:** P1  
**Stage:** 4  
The system shall allow users to submit physical count data for each product in the reconciliation session.

| Field | Type | Required | Constraints |
|---|---|---|---|
| `reconciliation_id` | FK | Yes | Must reference an active reconciliation session |
| `product_id` | FK | Yes | Must be a product in the count scope |
| `physical_quantity` | Integer | Yes | >= 0 |
| `batch_number` | String | No | If batch-level reconciliation is needed |
| `counted_by` | FK | Auto | User submitting the count |
| `counted_at` | DateTime | Auto | Timestamp |
| `notes` | String | No | Observations (e.g., "damaged packaging", "wrong shelf") |

---

#### FR-IR-003 — Discrepancy Report
**Priority:** P1  
**Stage:** 4  
Once physical counts are submitted, the system shall automatically generate a discrepancy report:

| Field | Description |
|---|---|
| `product_id` | Product with discrepancy |
| `product_name` | Product name and SKU |
| `system_quantity` | What the system recorded |
| `physical_quantity` | What was physically counted |
| `variance` | physical_quantity - system_quantity |
| `variance_percentage` | (variance / system_quantity) × 100 |
| `variance_type` | `surplus` (physical > system), `shortage` (physical < system), `match` (equal) |
| `estimated_value_impact` | variance × unit_cost |

**Summary metrics:**
- Total products counted
- Products with discrepancies (count and percentage)
- Total value of discrepancies (positive and negative)
- Inventory accuracy rate = (products with match / total products counted) × 100

---

#### FR-IR-004 — Approve and Apply Adjustments
**Priority:** P1  
**Stage:** 4  
The system shall allow authorized users (Admin, Warehouse Manager) to review the discrepancy report and:

1. **Approve all adjustments** — apply all physical counts as the new system quantities
2. **Approve selectively** — approve individual product adjustments and flag others for re-count
3. **Reject and re-count** — mark specific products for a second physical count

**On approval:**
- For each approved discrepancy, create an inventory adjustment (type: `reconciliation`) via FR-IM-004
- Record the adjustment in inventory movement history with `reference_id` linking to the reconciliation session
- Update the inventory record to match the physical count
- Log the approval in the audit trail (FR-AD-002)

---

#### FR-IR-005 — Reconciliation History
**Priority:** P1  
**Stage:** 4  
The system shall maintain a complete history of all reconciliation sessions per warehouse, including:
- Date of reconciliation
- Scope and coverage
- Inventory accuracy rate achieved
- Total value of adjustments (surplus and shortage separately)
- Trend: accuracy rate over time (is the warehouse getting better or worse?)

---

#### FR-IR-006 — Reconciliation Scheduling
**Priority:** P2  
**Stage:** 6  
The system shall support configurable reconciliation schedules:
- **Full reconciliation:** Monthly or quarterly for all products in a warehouse
- **Cycle counting:** Daily reconciliation of a rotating subset of products (e.g., reconcile 5% of products per day, covering 100% over 20 business days)
- **ABC-driven:** A-class products reconciled weekly, B-class monthly, C-class quarterly

Scheduled reconciliations shall automatically create sessions via the background job scheduler (FR-BJ-004).

---

### 3.17 System Events and Business Workflows

**Business Context:** In any enterprise system, actions do not happen in isolation. A single business event — like recording a sale or receiving a purchase order — triggers a cascade of downstream effects across multiple modules. If these cascades are not explicitly defined, the system becomes a collection of disconnected CRUD endpoints instead of an integrated platform.

This section defines the event-driven workflows that connect OptiStock's modules into a cohesive system.

---

#### FR-SE-001 — Sale Recorded Event
**Priority:** P0  
**Stage:** 1  
When a sale is recorded (FR-SA-001), the system shall execute the following cascade:

```
Sale Recorded
  │
  ├── 1. Create inventory adjustment (type: 'sold') → FR-IM-004
  │     └── Inventory movement logged → FR-IM-005
  │
  ├── 2. Check: available_quantity <= min_stock_level?
  │     ├── Yes → Create low stock alert → FR-NF-001
  │     │         └── Flag product for recommendation engine → FR-RC-001
  │     └── No → Continue
  │
  ├── 3. Update customer lifetime value (if customer_id provided) → FR-CU-002
  │
  ├── 4. Update warehouse utilization metrics → FR-WH-002
  │
  └── 5. Log audit entry: 'sale.created' → FR-AD-002
```

---

#### FR-SE-002 — Purchase Order Delivered Event
**Priority:** P0  
**Stage:** 1  
When a PO transitions to `delivered` (FR-PO-004), the system shall execute:

```
PO Marked as Delivered
  │
  ├── 1. For each line item:
  │     ├── Create inventory adjustment (type: 'received') → FR-IM-004
  │     │     └── Inventory movement logged → FR-IM-005
  │     └── Check: was product previously 'low_stock' or 'out_of_stock'?
  │           └── Yes → Resolve related low stock alert → FR-NF-006
  │
  ├── 2. Calculate delivery_delay_days
  │     ├── If late → Record negative supplier event
  │     └── Update supplier performance metrics → FR-SP-005
  │
  ├── 3. Update warehouse utilization → FR-WH-002
  │
  ├── 4. Check: warehouse utilization > 85%?
  │     └── Yes → Create warehouse capacity alert → FR-NF-005
  │
  └── 5. Log audit entry: 'purchase_order.delivered' → FR-AD-002
```

---

#### FR-SE-003 — Transfer Completed Event
**Priority:** P1  
**Stage:** 3  
When a transfer transitions to `completed` (FR-WH-005), the system shall execute:

```
Transfer Completed
  │
  ├── 1. Source warehouse:
  │     ├── Create inventory adjustment (type: 'transferred_out') → FR-IM-004
  │     └── Check: source product now low_stock?
  │           └── Yes → Create low stock alert
  │
  ├── 2. Destination warehouse:
  │     ├── Create inventory adjustment (type: 'transferred_in') → FR-IM-004
  │     └── Check: destination warehouse > 85% capacity?
  │           └── Yes → Create warehouse capacity alert
  │
  ├── 3. Resolve related transfer recommendation (if exists) → FR-RC-004
  │
  └── 4. Log audit entry: 'transfer.completed' → FR-AD-002
```

---

#### FR-SE-004 — Reconciliation Approved Event
**Priority:** P1  
**Stage:** 4  
When reconciliation adjustments are approved (FR-IR-004), the system shall execute:

```
Reconciliation Approved
  │
  ├── 1. For each approved discrepancy:
  │     ├── Create inventory adjustment (type: 'reconciliation') → FR-IM-004
  │     └── Inventory movement logged with reconciliation_id → FR-IM-005
  │
  ├── 2. Recalculate warehouse utilization → FR-WH-002
  │
  ├── 3. Check for newly triggered alerts:
  │     ├── Any product now low_stock? → FR-NF-001
  │     └── Any product now overstock? → flag for recommendation
  │
  ├── 4. Update inventory accuracy KPI → FR-AN-004
  │
  └── 5. Log audit entry: 'reconciliation.approved' → FR-AD-002
```

---

#### FR-SE-005 — Recommendation Accepted Event
**Priority:** P2  
**Stage:** 8  
When a user accepts a recommendation (FR-RC-004), the system shall execute:

```
Recommendation Accepted
  │
  ├── Type: 'reorder'
  │     └── Pre-fill a draft Purchase Order with:
  │           supplier_id, warehouse_id, product_id, quantity from recommendation
  │
  ├── Type: 'transfer'
  │     └── Pre-fill a draft Transfer Request with:
  │           source_warehouse, dest_warehouse, product_id, quantity
  │
  ├── Type: 'switch_supplier'
  │     └── Flag current supplier for review
  │           Create a comparison report with recommended alternative
  │
  ├── Type: 'discount'
  │     └── Create a pricing adjustment draft (if pricing module exists)
  │           Otherwise, flag for manual action
  │
  └── Log audit entry: 'recommendation.accepted' → FR-AD-002
```

---

### 3.18 Background Jobs and Scheduling

**Business Context:** An intelligent system cannot rely on users clicking buttons to trigger analysis. Forecasts must be regenerated as new sales data arrives. Recommendations must be refreshed nightly. Expired tokens must be cleaned up. These are the jobs that run while nobody is watching — and they are what make the platform feel alive and proactive.

---

#### FR-BJ-001 — Nightly Recommendation Generation
**Priority:** P2  
**Stage:** 8  
The system shall run the recommendation engine as a scheduled background job.

| Parameter | Value |
|---|---|
| Schedule | Daily at 02:00 AM (configurable) |
| Scope | All active products across all active warehouses |
| Timeout | 30 minutes max |
| Retry | 3 attempts with exponential backoff |
| Logging | Job start/end, products analyzed, recommendations generated, errors |

**Job steps:**
1. Expire stale recommendations (status: `pending`, age > 7 days)
2. Fetch current inventory state across all warehouses
3. Fetch latest demand forecasts
4. Run optimization calculations (EOQ, ROP, Safety Stock)
5. Evaluate supplier performance scores
6. Apply recommendation rules (FR-RC-001)
7. Deduplicate — do not create a recommendation if an identical `pending` one already exists
8. Persist new recommendations
9. Log summary: `{products_analyzed: N, recommendations_generated: M, elapsed_ms: X}`

---

#### FR-BJ-002 — Weekly Demand Forecast Refresh
**Priority:** P2  
**Stage:** 7  
The system shall regenerate demand forecasts on a weekly schedule.

| Parameter | Value |
|---|---|
| Schedule | Sunday at 03:00 AM (configurable) |
| Scope | All active products with >= 12 weeks of sales history |
| Timeout | 60 minutes max |
| Retry | 3 attempts |

**Job steps:**
1. Identify products eligible for forecasting (sufficient sales history)
2. For each product: run model selection via backtesting
3. Generate forecasts for the configured horizon (default: 4 weeks)
4. Store forecasts in the forecast table
5. Compare previous forecasts to actual sales (for accuracy tracking — FR-FC-002)
6. Log summary: `{products_forecasted: N, avg_mape: X, models_used: {...}}`

---

#### FR-BJ-003 — Weekly ABC Reclassification
**Priority:** P1  
**Stage:** 4  
The system shall reclassify products using ABC analysis on a weekly schedule.

| Parameter | Value |
|---|---|
| Schedule | Monday at 01:00 AM (configurable) |
| Scope | All active products with sales in the last 90 days |
| Timeout | 10 minutes |

**Job steps:**
1. Calculate total revenue per product over the analysis period (default: 90 days)
2. Sort products by revenue descending
3. Assign classes: A (top 80% cumulative revenue), B (next 15%), C (remaining 5%)
4. Update product classification in database
5. Generate classification change log (products that moved between classes)
6. Log summary

---

#### FR-BJ-004 — Reconciliation Cycle Count Scheduler
**Priority:** P2  
**Stage:** 6  
The system shall automatically create reconciliation sessions based on configured cycle counting rules (FR-IR-006).

| Parameter | Value |
|---|---|
| Schedule | Daily at 06:00 AM (configurable) |
| Scope | Per-warehouse, based on counting strategy |

**Job steps:**
1. For each warehouse with cycle counting enabled:
   - Determine which products are due for counting (based on ABC class and last count date)
   - Create a reconciliation session (FR-IR-001) with scope: `sample`
   - Assign to the warehouse's designated counter (if configured)
2. Log summary: `{sessions_created: N, products_to_count: M}`

---

#### FR-BJ-005 — Expiry Alert Scanner
**Priority:** P1  
**Stage:** 3  
The system shall scan for expiring inventory daily.

| Parameter | Value |
|---|---|
| Schedule | Daily at 07:00 AM |
| Scope | All inventory records with non-null expiry_date |

**Job steps:**
1. Identify batches expiring within 7, 30, and 90 days
2. Generate or update alerts per FR-IM-007
3. Flag expired batches (expiry_date < today) — update status, exclude from available quantity
4. Log summary

---

#### FR-BJ-006 — Supplier Score Recalculation
**Priority:** P2  
**Stage:** 7  
The system shall recalculate supplier reliability scores daily.

| Parameter | Value |
|---|---|
| Schedule | Daily at 04:00 AM |
| Scope | All active suppliers with at least 1 delivered PO |

**Job steps:**
1. For each supplier: recalculate reliability_score per FR-SP-005
2. If score dropped below 0.5 since last calculation → generate alert (FR-NF-003)
3. Update supplier records
4. Log summary

---

#### FR-BJ-007 — Data Cleanup Jobs
**Priority:** P1  
**Stage:** 3  
The system shall run periodic cleanup of transient data.

| Job | Schedule | Action |
|---|---|---|
| Expired refresh tokens | Daily at 05:00 AM | Delete tokens where `expires_at` < now - 30 days |
| Stale import sessions | Daily at 05:00 AM | Delete unconfirmed import sessions older than 24 hours |
| Expired recommendations | Daily (part of FR-BJ-001) | Set status to `expired` for `pending` recommendations older than 7 days |

---

#### FR-BJ-008 — Dead Stock Detection Job
**Priority:** P2  
**Stage:** 4  
The system shall identify dead stock on a weekly schedule.

| Parameter | Value |
|---|---|
| Schedule | Monday at 01:30 AM |
| Scope | All inventory records with quantity > 0 |

**Job steps:**
1. For each product-warehouse combination: check if any sales exist in the last N days (configurable, default: 90)
2. If no sales → flag as dead stock
3. Calculate holding cost: quantity × unit_cost × (holding_rate / 365) × days_since_last_sale
4. Update dead stock records
5. Log summary

---

#### FR-BJ-009 — Overdue PO Scanner
**Priority:** P1  
**Stage:** 3  
The system shall check for overdue purchase orders daily.

| Parameter | Value |
|---|---|
| Schedule | Daily at 08:00 AM |
| Scope | POs with status in (`submitted`, `confirmed`, `shipped`) |

**Job steps:**
1. Identify POs where `expected_delivery_date` < today
2. Generate overdue alerts (FR-NF-002)
3. Escalate: if PO is overdue by > 7 days, set alert severity to `critical`
4. Log summary

---

#### FR-BJ-010 — Job Execution Framework
**Priority:** P1  
**Stage:** 3 (basic) / Stage 6 (Airflow)  
All background jobs shall conform to a standard execution framework:

| Aspect | Requirement |
|---|---|
| Scheduling | Configurable cron expressions |
| Logging | Every job logs: start_time, end_time, status (success/failure), items_processed, errors |
| Retry | Configurable retry count (default: 3) with exponential backoff |
| Timeout | Configurable per-job timeout |
| Idempotency | Re-running a job for the same date shall not create duplicate records |
| Monitoring | Job execution history stored in database, queryable via admin API |
| Alerting | Failed jobs (after all retries exhausted) shall generate a system alert |

**Implementation progression:**
- Stages 3–5: Python scripts with APScheduler or simple cron
- Stage 6+: Apache Airflow DAGs with dependency management, monitoring UI, and retry orchestration

---

## 4. Non-Functional Requirements

> Note: Detailed performance and SLA targets are defined in BRD Section 7. The requirements below define the technical mechanisms to achieve those targets.

---

#### NFR-001 — Response Time
**Priority:** P0  
The system shall meet the following response time targets:
- Standard CRUD endpoints: < 200ms average
- Analytics/aggregation endpoints: < 500ms average
- Report generation endpoints: < 5 seconds
- Recommendation generation: < 2 seconds per request

---

#### NFR-002 — Pagination
**Priority:** P0  
All list endpoints shall support pagination. No endpoint shall return more than 100 records in a single response without explicit pagination.

---

#### NFR-003 — Error Handling
**Priority:** P0  
All API errors shall return a consistent JSON structure:

```json
{
  "error": {
    "code": "PRODUCT_NOT_FOUND",
    "message": "Product with ID 123 was not found.",
    "details": {},
    "timestamp": "2026-07-01T10:00:00Z",
    "request_id": "uuid-v4"
  }
}
```

HTTP status codes shall follow REST conventions:
- 200: Success
- 201: Created
- 204: Deleted (no content)
- 400: Bad Request (validation error)
- 401: Unauthorized
- 403: Forbidden (insufficient permissions)
- 404: Not Found
- 409: Conflict (duplicate, business rule violation)
- 422: Unprocessable Entity
- 429: Too Many Requests
- 500: Internal Server Error

---

#### NFR-004 — Logging
**Priority:** P1  
The system shall produce structured JSON logs containing:
- Timestamp (ISO 8601)
- Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Request ID (for tracing)
- User ID (if authenticated)
- Module/component name
- Message
- Additional context (as JSON)

Sensitive data (passwords, tokens, PII) shall never appear in logs.

---

#### NFR-005 — Database Connection Pooling
**Priority:** P1  
The system shall use connection pooling for PostgreSQL. Default pool size: 10 connections. Maximum pool size: 20 connections. Connection timeout: 5 seconds.

---

#### NFR-006 — Input Validation
**Priority:** P0  
All user inputs shall be validated before processing. The system shall use Pydantic models for request validation in FastAPI.

---

#### NFR-007 — CORS
**Priority:** P1  
The system shall support configurable CORS (Cross-Origin Resource Sharing) policies. Default: restrict to the dashboard's origin. Configurable via environment variables.

---

#### NFR-008 — Environment Configuration
**Priority:** P0  
All configuration (database credentials, JWT secret, API keys, feature flags) shall be loaded from environment variables. No secrets shall be hardcoded in source code.

---

#### NFR-009 — Database Migrations
**Priority:** P0  
All database schema changes shall be managed through versioned migration scripts (using Alembic). Migrations shall be reversible (up and down).

---

#### NFR-010 — API Documentation
**Priority:** P0  
The system shall auto-generate interactive API documentation via FastAPI's built-in Swagger UI (available at `/docs`) and ReDoc (available at `/redoc`).

---

#### NFR-011 — Containerization
**Priority:** P1  
Every service (backend, database, Redis) shall be containerized with Docker. The entire application shall be orchestrable via a single `docker-compose.yml` file.

---

#### NFR-012 — Testing
**Priority:** P1  
The system shall maintain:
- Unit tests for service layer logic
- Integration tests for API endpoints
- Test coverage target: >= 70% for core modules

---

#### NFR-013 — Idempotency
**Priority:** P1  
Write operations that may be retried (purchase order creation, stock adjustments) should support idempotency via client-generated idempotency keys to prevent duplicate processing.

---

---

## 5. Data Requirements

### 5.1 Data Volume Estimates by Stage

| Stage | Products | Warehouses | Sales Records | Users |
|---|---|---|---|---|
| 1–4 | 500 | 5 | 10,000 | 10 |
| 5–8 | 20,000 | 25 | 1,000,000 | 50 |
| 9–12 | 5,000,000 | 200 | 100,000,000 | 1,000 |

### 5.2 Data Retention

| Data Type | Retention | Rationale |
|---|---|---|
| Inventory movements | Indefinite | Audit trail, never deleted |
| Sales records | Indefinite | Required for forecasting and analytics |
| Audit logs | Indefinite | Compliance and accountability |
| Forecasts | 2 years | Accuracy comparison requires historical forecasts |
| Recommendations | 1 year | Expired recommendations can be archived |
| Session/refresh tokens | 30 days after expiry | Clean up stale tokens |

### 5.3 Data Integrity

- All foreign key relationships shall be enforced at the database level
- All monetary values shall use `DECIMAL(12,2)` — never floating point
- All timestamps shall be stored in UTC
- All date-only fields shall use `DATE` type (no time component)
- Soft deletes shall be used for all business entities; hard deletes only for system-managed data (tokens, cache)

---

## 6. External Interface Requirements

### 6.1 API Format

- Protocol: HTTP/HTTPS
- Format: JSON (request and response bodies)
- Content-Type: `application/json`
- Character encoding: UTF-8
- API versioning: URL prefix (`/api/v1/`)
- Date format in JSON: ISO 8601 (`2026-07-01T10:00:00Z`)

### 6.2 File Upload Interface

- Protocol: HTTP multipart/form-data
- Supported formats: `.csv`, `.xlsx`
- Maximum file size: 50MB
- Response: Import summary with success/failure counts

### 6.3 Dashboard Interface

The backend shall expose REST APIs consumed by a frontend dashboard. The backend is frontend-agnostic — any frontend framework (React, Vue, Power BI) can consume the APIs.

---

## 7. Traceability Matrix

This matrix maps functional requirements to business objectives from the BRD.

| Business Objective (BRD) | Supporting Requirements |
|---|---|
| Reduce stockouts | FR-IM-006, FR-FC-001, FR-OP-002, FR-RC-001 (reorder), FR-NF-001, FR-SE-001 |
| Reduce overstock | FR-IM-008, FR-AN-002, FR-RC-001 (reduce_order), FR-OP-001, FR-BJ-008 |
| Improve supplier accountability | FR-SP-005, FR-SP-006, FR-AN-006, FR-RC-001 (switch_supplier), FR-NF-003, FR-BJ-006 |
| Optimize warehouse utilization | FR-WH-005, FR-WH-006, FR-OP-004, FR-RC-001 (transfer), FR-NF-005, FR-SE-003 |
| Accelerate decision-making | FR-RC-001 through FR-RC-005, FR-AN-007, FR-BJ-001 |
| Centralize inventory data | FR-ET-001 through FR-ET-005, FR-IM-001 through FR-IM-003 |
| Enable demand forecasting | FR-FC-001 through FR-FC-004, FR-BJ-002 |
| Eliminate dead inventory | FR-IM-008, FR-RC-001 (discontinue, discount), FR-BJ-008 |
| Prevent expiry losses | FR-IM-007, FR-NF-004, FR-RC-001 (expiry_action), FR-BJ-005 |
| Improve inventory accuracy | FR-IR-001 through FR-IR-006, FR-IM-004, FR-IM-005, FR-AD-002, FR-SE-004 |

---

## 8. Appendix

### 8.1 API Endpoint Summary

| Method | Endpoint | Module | Stage |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Auth | 2 |
| POST | `/api/v1/auth/login` | Auth | 2 |
| POST | `/api/v1/auth/refresh` | Auth | 2 |
| POST | `/api/v1/auth/logout` | Auth | 2 |
| PUT | `/api/v1/auth/password` | Auth | 2 |
| | | | |
| GET | `/api/v1/products` | Products | 1 |
| POST | `/api/v1/products` | Products | 1 |
| GET | `/api/v1/products/{id}` | Products | 1 |
| PATCH | `/api/v1/products/{id}` | Products | 1 |
| DELETE | `/api/v1/products/{id}` | Products | 1 |
| GET | `/api/v1/products/search` | Products | 3 |
| GET | `/api/v1/products/{id}/history` | Products | 3 |
| | | | |
| GET | `/api/v1/inventory` | Inventory | 1 |
| POST | `/api/v1/inventory` | Inventory | 1 |
| GET | `/api/v1/inventory/{id}` | Inventory | 1 |
| POST | `/api/v1/inventory/{id}/adjust` | Inventory | 1 |
| GET | `/api/v1/inventory/{id}/movements` | Inventory | 1 |
| GET | `/api/v1/inventory/low-stock` | Inventory | 1 |
| GET | `/api/v1/inventory/expiring` | Inventory | 3 |
| GET | `/api/v1/inventory/dead-stock` | Inventory | 4 |
| GET | `/api/v1/inventory/valuation` | Inventory | 4 |
| | | | |
| GET | `/api/v1/warehouses` | Warehouses | 1 |
| POST | `/api/v1/warehouses` | Warehouses | 1 |
| GET | `/api/v1/warehouses/{id}` | Warehouses | 1 |
| PATCH | `/api/v1/warehouses/{id}` | Warehouses | 1 |
| POST | `/api/v1/transfers` | Warehouses | 3 |
| GET | `/api/v1/transfers` | Warehouses | 3 |
| PATCH | `/api/v1/transfers/{id}` | Warehouses | 3 |
| GET | `/api/v1/warehouses/utilization` | Warehouses | 4 |
| | | | |
| GET | `/api/v1/suppliers` | Suppliers | 1 |
| POST | `/api/v1/suppliers` | Suppliers | 1 |
| GET | `/api/v1/suppliers/{id}` | Suppliers | 1 |
| PATCH | `/api/v1/suppliers/{id}` | Suppliers | 1 |
| GET | `/api/v1/suppliers/compare` | Suppliers | 7 |
| | | | |
| GET | `/api/v1/purchase-orders` | PO | 1 |
| POST | `/api/v1/purchase-orders` | PO | 1 |
| GET | `/api/v1/purchase-orders/{id}` | PO | 1 |
| PATCH | `/api/v1/purchase-orders/{id}/status` | PO | 1 |
| GET | `/api/v1/purchase-orders/overdue` | PO | 3 |
| | | | |
| GET | `/api/v1/sales` | Sales | 1 |
| POST | `/api/v1/sales` | Sales | 1 |
| GET | `/api/v1/sales/{id}` | Sales | 1 |
| GET | `/api/v1/sales/summary` | Sales | 4 |
| | | | |
| GET | `/api/v1/customers` | Customers | 1 |
| POST | `/api/v1/customers` | Customers | 1 |
| GET | `/api/v1/customers/{id}` | Customers | 1 |
| PATCH | `/api/v1/customers/{id}` | Customers | 1 |
| | | | |
| GET | `/api/v1/analytics/inventory-turnover` | Analytics | 4 |
| GET | `/api/v1/analytics/abc-classification` | Analytics | 4 |
| GET | `/api/v1/analytics/revenue` | Analytics | 4 |
| GET | `/api/v1/analytics/inventory-health` | Analytics | 4 |
| GET | `/api/v1/analytics/warehouse-comparison` | Analytics | 4 |
| GET | `/api/v1/analytics/supplier-performance` | Analytics | 7 |
| GET | `/api/v1/analytics/executive-summary` | Analytics | 8 |
| | | | |
| POST | `/api/v1/import/{entity}` | ETL | 5 |
| POST | `/api/v1/import/{entity}/confirm` | ETL | 5 |
| GET | `/api/v1/export/{entity}` | ETL | 5 |
| | | | |
| GET | `/api/v1/forecasts` | Forecast | 7 |
| POST | `/api/v1/forecasts/generate` | Forecast | 7 |
| GET | `/api/v1/forecasts/{product_id}` | Forecast | 7 |
| GET | `/api/v1/forecasts/accuracy` | Forecast | 7 |
| | | | |
| GET | `/api/v1/recommendations` | Recommendations | 8 |
| GET | `/api/v1/recommendations/{id}` | Recommendations | 8 |
| PATCH | `/api/v1/recommendations/{id}/action` | Recommendations | 8 |
| | | | |
| GET | `/api/v1/alerts` | Alerts | 3 |
| GET | `/api/v1/alerts/{id}` | Alerts | 3 |
| PATCH | `/api/v1/alerts/{id}/acknowledge` | Alerts | 3 |
| PATCH | `/api/v1/alerts/{id}/resolve` | Alerts | 3 |
| | | | |
| POST | `/api/v1/reconciliation` | Reconciliation | 4 |
| GET | `/api/v1/reconciliation` | Reconciliation | 4 |
| GET | `/api/v1/reconciliation/{id}` | Reconciliation | 4 |
| POST | `/api/v1/reconciliation/{id}/counts` | Reconciliation | 4 |
| GET | `/api/v1/reconciliation/{id}/discrepancies` | Reconciliation | 4 |
| POST | `/api/v1/reconciliation/{id}/approve` | Reconciliation | 4 |
| GET | `/api/v1/reconciliation/history` | Reconciliation | 4 |
| | | | |
| GET | `/api/v1/admin/users` | Admin | 2 |
| POST | `/api/v1/admin/users` | Admin | 2 |
| PATCH | `/api/v1/admin/users/{id}` | Admin | 2 |
| GET | `/api/v1/admin/audit-log` | Admin | 3 |
| GET | `/api/v1/admin/config` | Admin | 9 |
| PATCH | `/api/v1/admin/config` | Admin | 9 |
| GET | `/api/v1/admin/jobs` | Admin | 6 |
| GET | `/api/v1/admin/jobs/{id}/history` | Admin | 6 |
| POST | `/api/v1/admin/jobs/{id}/trigger` | Admin | 6 |
| GET | `/health` | System | 3 |

---

## Document Approval

| Role | Name | Date | Status |
|---|---|---|---|
| Project Owner | — | — | Pending |
| Technical Lead | — | — | Pending |

---

*This document will be updated as requirements evolve. All changes will be tracked with version numbers and dates.*
