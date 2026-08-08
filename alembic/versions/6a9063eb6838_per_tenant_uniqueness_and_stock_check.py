"""per_tenant_uniqueness_and_stock_check

Fixes two schema defects found by the test suite:

1. ``Inventory.quantity`` declares ``CheckConstraint("quantity >= 0")`` on the
   SQLAlchemy model, but no migration ever created it. A model-level constraint
   is inert — it is only a instruction for generating DDL. The database was
   therefore accepting negative stock, and the sole protection against ghost
   stock was the application-level check in ``InventoryService.adjust_inventory``.

2. ``products.sku`` and ``warehouses.location_code`` carried GLOBAL unique
   indexes, contradicting both the service rule ("SKUs must be unique per
   company") and ``ProductRepository.get_by_sku``, whose docstring states two
   companies may each have a "MUG-01". The practical effect was cross-tenant
   denial of service: the first tenant to register a common code permanently
   denied it to every other tenant, and the resulting IntegrityError surfaced as
   an opaque 500. Replaced with composite ``(company_id, <code>)`` uniqueness.

Revision ID: 6a9063eb6838
Revises: a8717e91327e
Create Date: 2026-08-06 11:02:08.573033

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6a9063eb6838'
down_revision: Union[str, None] = 'a8717e91327e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Enforce non-negative stock at the database level -----------------
    op.create_check_constraint(
        "check_qty_non_negative", "inventory", "quantity >= 0"
    )

    # --- 2. Make product SKUs unique per tenant, not globally ----------------
    op.drop_index("ix_products_sku", table_name="products")
    # Keep a non-unique index so lookups by sku stay fast.
    op.create_index("ix_products_sku", "products", ["sku"], unique=False)
    op.create_unique_constraint(
        "uix_product_company_sku", "products", ["company_id", "sku"]
    )

    # --- 3. Same for warehouse location codes --------------------------------
    op.drop_index("ix_warehouses_location_code", table_name="warehouses")
    op.create_index(
        "ix_warehouses_location_code", "warehouses", ["location_code"], unique=False
    )
    op.create_unique_constraint(
        "uix_warehouse_company_location", "warehouses", ["company_id", "location_code"]
    )


def downgrade() -> None:
    # NOTE: reverting to global uniqueness will fail if two tenants have since
    # registered the same code. That is expected — it is the bug being undone.
    op.drop_constraint(
        "uix_warehouse_company_location", "warehouses", type_="unique"
    )
    op.drop_index("ix_warehouses_location_code", table_name="warehouses")
    op.create_index(
        "ix_warehouses_location_code", "warehouses", ["location_code"], unique=True
    )

    op.drop_constraint("uix_product_company_sku", "products", type_="unique")
    op.drop_index("ix_products_sku", table_name="products")
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)

    op.drop_constraint("check_qty_non_negative", "inventory", type_="check")
