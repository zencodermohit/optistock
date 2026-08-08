"""analytics_persistence_columns

Gives the analytics layer somewhere to write its results. Until now
``run_abc_analysis`` and ``run_demand_forecast`` returned DataFrames that nothing
consumed, so the entire ML/analytics feature set produced no observable output.

- ``products.abc_class`` / ``abc_calculated_at`` — destination for the nightly
  Pareto classification. Nullable: a product has no class until it has appeared
  in a completed sale.
- ``recommendations.source`` — distinguishes pipeline-generated rows from ones a
  human created, so the nightly job can replace its own previous output without
  deleting anybody's manual entries.

Revision ID: d168f4adcb13
Revises: 6a9063eb6838
Create Date: 2026-08-06 11:21:56.374165

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd168f4adcb13'
down_revision: Union[str, None] = '6a9063eb6838'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("products", sa.Column("abc_class", sa.String(length=1), nullable=True))
    op.add_column(
        "products",
        sa.Column("abc_calculated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Index supports the common "show me all A-class items" filter per tenant.
    op.create_index(
        "ix_products_company_abc_class", "products", ["company_id", "abc_class"]
    )

    # server_default backfills existing rows in the same statement; the column can
    # therefore be NOT NULL immediately without a separate UPDATE pass.
    op.add_column(
        "recommendations",
        sa.Column(
            "source",
            sa.String(length=50),
            nullable=False,
            server_default="manual",
        ),
    )
    op.create_index(
        "ix_recommendations_source_target",
        "recommendations",
        ["source", "product_id", "warehouse_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_recommendations_source_target", table_name="recommendations")
    op.drop_column("recommendations", "source")

    op.drop_index("ix_products_company_abc_class", table_name="products")
    op.drop_column("products", "abc_calculated_at")
    op.drop_column("products", "abc_class")
