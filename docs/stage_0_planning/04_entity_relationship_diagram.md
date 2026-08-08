# OptiStock — Database Entity-Relationship Diagram

> **OptiStock — Enterprise Inventory Intelligence Platform**

**Document Version:** 1.0  
**Date:** 2026-07-01  
**Author:** OptiStock Engineering Team  
**Status:** Draft — Pending Technical Review  
**Reference:** [Architecture v1.1](./03_architecture_document.md)

---

## 1. Core Principles

Before looking at the schema, understand these rules which apply to the entire database:

1. **Multi-Tenancy (Future Proofing):** Every core table includes a `company_id`. While Stage 1 builds for a single company, this ensures we don't have to rewrite the database if we transition to a SaaS model.
2. **Auditability:** Tables do not use `DELETE` (except for transient data like sessions). We use `is_active` or `status` flags (soft deletes) to preserve historical integrity.
3. **Immutability of Transactions:** Records in `sales`, `inventory_movements`, and `purchase_orders` are immutable. Mistakes are fixed via reversing transactions, not `UPDATE` statements.
4. **Data Types Matter:** Monetary values are `DECIMAL(12,2)`. Identifiers are `UUID` or `BIGINT`. Timestamps are `TIMESTAMPTZ` (UTC).
5. **Database constraints > Code validation:** Foreign keys, unique constraints, and check constraints (e.g., `quantity >= 0`) are enforced at the database level.

---

## 2. Entity-Relationship Diagram

*This diagram represents the schema for Stage 1 through Stage 8.*

```mermaid
erDiagram
    %% Core Entities
    COMPANIES ||--o{ USERS : employs
    COMPANIES ||--o{ WAREHOUSES : owns
    COMPANIES ||--o{ PRODUCTS : sells
    COMPANIES ||--o{ SUPPLIERS : buys_from
    COMPANIES ||--o{ CUSTOMERS : sells_to

    %% User & Auth
    USERS ||--o{ REFRESH_TOKENS : has
    USERS ||--o{ AUDIT_LOGS : performs

    %% Product & Inventory
    PRODUCTS ||--o{ INVENTORY : stocked_as
    WAREHOUSES ||--o{ INVENTORY : holds
    PRODUCTS ||--o{ PRODUCT_HISTORY : tracks_changes

    %% Transactions
    INVENTORY ||--o{ INVENTORY_MOVEMENTS : records
    USERS ||--o{ INVENTORY_MOVEMENTS : authorized_by

    %% Purchasing
    SUPPLIERS ||--o{ PURCHASE_ORDERS : fulfills
    WAREHOUSES ||--o{ PURCHASE_ORDERS : receives
    PURCHASE_ORDERS ||--|{ PO_ITEMS : contains
    PRODUCTS ||--o{ PO_ITEMS : requested_in

    %% Sales
    CUSTOMERS ||--o{ SALES : makes
    WAREHOUSES ||--o{ SALES : fulfilled_from
    SALES ||--|{ SALE_ITEMS : contains
    PRODUCTS ||--o{ SALE_ITEMS : sold_in

    %% Intelligence & Optimization
    PRODUCTS ||--o{ FORECASTS : predicted_for
    PRODUCTS ||--o{ RECOMMENDATIONS : target
    WAREHOUSES ||--o{ RECOMMENDATIONS : context

    %% Reconciliation
    WAREHOUSES ||--o{ RECONCILIATION_SESSIONS : conducts
    RECONCILIATION_SESSIONS ||--o{ RECONCILIATION_COUNTS : contains
    PRODUCTS ||--o{ RECONCILIATION_COUNTS : counted_for
    USERS ||--o{ RECONCILIATION_SESSIONS : assigned_to

    %% Schema Definitions

    COMPANIES {
        uuid id PK
        string name
        boolean is_active
        timestamp created_at
    }

    USERS {
        uuid id PK
        uuid company_id FK
        string email UK
        string password_hash
        string full_name
        string role "admin, warehouse_mgr, etc."
        boolean is_active
        timestamp created_at
    }

    WAREHOUSES {
        uuid id PK
        uuid company_id FK
        string name
        string location_code UK
        int capacity_units
        boolean is_active
    }

    PRODUCTS {
        uuid id PK
        uuid company_id FK
        string sku UK
        string name
        string category
        decimal unit_cost
        decimal selling_price
        int min_stock_level
        string abc_class "A, B, C"
        boolean is_active
    }

    SUPPLIERS {
        uuid id PK
        uuid company_id FK
        string name
        string contact_email
        int average_lead_time_days
        decimal reliability_score "0.0 to 1.0"
        boolean is_active
    }

    INVENTORY {
        uuid id PK
        uuid product_id FK
        uuid warehouse_id FK
        int quantity "Must be >= 0"
        timestamp last_counted_at
        UNIQUE(product_id, warehouse_id)
    }

    INVENTORY_MOVEMENTS {
        uuid id PK
        uuid inventory_id FK
        uuid user_id FK "Who authorized it"
        string type "received, sold, transferred, adjusted, reconciliation"
        int quantity_change "+ or -"
        int quantity_after
        string reference_id "PO ID, Sale ID, etc."
        timestamp created_at
    }

    PURCHASE_ORDERS {
        uuid id PK
        uuid company_id FK
        uuid supplier_id FK
        uuid destination_warehouse_id FK
        string status "draft, submitted, delivered, cancelled"
        date expected_delivery_date
        date actual_delivery_date
        decimal total_amount
        timestamp created_at
    }

    SALES {
        uuid id PK
        uuid company_id FK
        uuid customer_id FK "Nullable for walk-ins"
        uuid warehouse_id FK
        string status "completed, refunded"
        decimal total_amount
        timestamp sale_date
    }

    RECOMMENDATIONS {
        uuid id PK
        uuid company_id FK
        uuid product_id FK
        uuid warehouse_id FK
        string type "reorder, transfer, discount"
        string status "pending, accepted, rejected"
        jsonb reasoning "Explainability fields"
        decimal confidence
        timestamp generated_at
    }
```

---

## 3. Data Dictionary: Key Tables

### 3.1 The `inventory` Table
This is the heart of the system. It maintains the current state of stock.
- **Constraints:** `quantity >= 0` is enforced at the database level. Stock cannot go negative.
- **Locking:** When processing a sale or a PO delivery, the application must use `SELECT ... FOR UPDATE` to lock the inventory row, preventing race conditions where two simultaneous sales try to consume the last item.

### 3.2 The `inventory_movements` Table
This is the immutable ledger of all stock changes.
- **Why it matters:** If the `inventory` table says we have 50 units, the sum of `quantity_change` in `inventory_movements` for that item must also equal 50. If they don't match, the system has a data integrity bug.
- **Partitioning:** This table grows rapidly. It will be partitioned by `created_at` (monthly or quarterly) for efficient querying and data tiering.

### 3.3 The `recommendations` Table
This stores the output of the AI Engine.
- **The `reasoning` column:** Uses PostgreSQL's `JSONB` data type. This allows the AI engine to store structured explainability data (evidence, triggers, alternatives) without needing a rigid schema, while remaining queryable via SQL JSON operators.

---

## 4. Archival & Tiering Implementation

As defined in Architecture v1.1, we use table partitioning for data tiering.

### 4.1 Tables Subject to Partitioning
Any table that records historical events will be partitioned by date:
- `sales` and `sale_items`
- `inventory_movements`
- `audit_logs`
- `forecasts` (historical predictions)

### 4.2 Partitioning Strategy Example
```sql
-- Create the parent table
CREATE TABLE inventory_movements (
    id UUID,
    inventory_id UUID,
    quantity_change INT,
    created_at TIMESTAMPTZ
) PARTITION BY RANGE (created_at);

-- Hot Tier (Current Quarter)
CREATE TABLE inventory_movements_q3_2026 
PARTITION OF inventory_movements 
FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');

-- Warm Tier (Previous Quarters)
CREATE TABLE inventory_movements_q2_2026 
PARTITION OF inventory_movements 
FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
```

**Benefits:**
1. Queries filtering by recent dates only scan the Hot partition (massive performance gain).
2. To "Archive" data to the Cold tier, an admin runs `ALTER TABLE ... DETACH PARTITION`. The data is instantly removed from the primary query path without a slow `DELETE` operation.
