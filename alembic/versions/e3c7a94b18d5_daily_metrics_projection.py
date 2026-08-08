"""Daily metrics projection.

Revision ID: e3c7a94b18d5
Revises: d2b8f5a71c04

A read model, not a source of truth. Every number in this table is derived from
sales and inventory_movements and can be thrown away and rebuilt -- which is the
point of a projection, and the reason it is safe to denormalise this
aggressively. If the shape turns out wrong, it is a rebuild rather than a
migration of real data.

It exists because the alternative is aggregating a year of sales on every
dashboard load. That query gets slower every day the business succeeds, and a
front page that degrades with growth is a front page that eventually nobody
opens.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "e3c7a94b18d5"
down_revision = "d2b8f5a71c04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column("company_id", UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column(
            "revenue", sa.Numeric(14, 2), nullable=False, server_default="0"
        ),
        sa.Column("orders", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units_sold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stock_movements", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("units_received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        # Composite primary key rather than a surrogate id. The natural key is
        # what an upsert needs to conflict on, and a projection row has no
        # identity beyond the company and day it summarises.
        sa.PrimaryKeyConstraint("company_id", "metric_date"),
    )

    # The dashboard always asks for one company's most recent N days, so the
    # index is ordered to serve that directly.
    op.create_index(
        "ix_daily_metrics_company_date",
        "daily_metrics",
        ["company_id", sa.text("metric_date DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_daily_metrics_company_date", table_name="daily_metrics")
    op.drop_table("daily_metrics")
