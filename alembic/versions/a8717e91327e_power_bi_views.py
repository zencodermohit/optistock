"""power_bi_views

Revision ID: a8717e91327e
Revises: 216fdc7fb463
Create Date: 2026-07-21 08:58:11.733043

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8717e91327e'
down_revision: Union[str, None] = '216fdc7fb463'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Current Stock Levels View
    op.execute("""
        CREATE VIEW current_stock_levels_view AS
        SELECT 
            i.id AS inventory_id,
            p.company_id,
            p.id AS product_id,
            p.sku,
            p.name AS product_name,
            p.category,
            w.name AS warehouse_name,
            i.quantity AS quantity_on_hand,
            i.last_counted_at
        FROM inventory i
        JOIN products p ON i.product_id = p.id
        JOIN warehouses w ON i.warehouse_id = w.id;
    """)

    # 2. Monthly Revenue View
    op.execute("""
        CREATE VIEW monthly_revenue_view AS
        SELECT 
            s.company_id,
            DATE_TRUNC('month', s.created_at) AS sale_month,
            p.category,
            p.sku,
            p.name AS product_name,
            SUM(si.quantity) AS total_quantity_sold,
            SUM(si.quantity * si.unit_price) AS total_revenue
        FROM sales s
        JOIN sale_items si ON s.id = si.sale_id
        JOIN products p ON si.product_id = p.id
        WHERE s.status = 'completed'
        GROUP BY 1, 2, 3, 4, 5;
    """)

    # 3. Supplier Performance View
    op.execute("""
        CREATE VIEW supplier_performance_view AS
        SELECT 
            po.company_id,
            s.id AS supplier_id,
            s.name AS supplier_name,
            s.reliability_score,
            COUNT(po.id) AS total_orders,
            SUM(CASE WHEN po.status = 'delivered' THEN 1 ELSE 0 END) AS fulfilled_orders,
            SUM(po.total_amount) AS total_spend
        FROM purchase_orders po
        JOIN suppliers s ON po.supplier_id = s.id
        GROUP BY 1, 2, 3, 4;
    """)

def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS supplier_performance_view;")
    op.execute("DROP VIEW IF EXISTS monthly_revenue_view;")
    op.execute("DROP VIEW IF EXISTS current_stock_levels_view;")
