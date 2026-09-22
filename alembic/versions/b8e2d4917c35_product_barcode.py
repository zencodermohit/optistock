"""Let a product carry the number printed on the article itself.

Until now the only identifier a product had was its SKU, which is ours. That is
enough for a keyboard and not enough for a camera: a phone pointed at a tin of
paint reads the manufacturer's EAN-13, and nothing in the schema could turn
that thirteen-digit string into a row. This column is that mapping.

NULLABLE, AND MOST ROWS WILL STAY NULL. Every product has a SKU because we
issue it. Almost none has a barcode here, because somebody has to physically
hold the article and scan it once. A schema that required the value would mean
inventing a fake barcode for every product nobody has scanned yet, which turns
a useful column into a column of noise.

UNIQUE PER COMPANY, NOT GLOBALLY, for the same reason the SKU is. Two tenants
stocking the same tin of paint both have a legitimate claim to its barcode, and
a global constraint would let whichever of them scanned it first lock the other
out of their own catalogue. Postgres permits repeated NULLs under a unique
constraint, so the unmapped majority costs nothing and the constraint still
does its job: within one company, one barcode means one product. Without it,
scanning becomes ambiguous exactly when it matters, because "which of these
three rows did I just scan" has no good answer at a warehouse door.

Revision ID: b8e2d4917c35
Revises: a7f31c9b02d4
"""

import sqlalchemy as sa
from alembic import op

revision = "b8e2d4917c35"
down_revision = "a7f31c9b02d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "barcode",
            sa.String(length=64),
            nullable=True,
            comment="EAN-13/UPC as printed on the article. Null until scanned.",
        ),
    )
    # Indexed because every scan is a lookup by this value and nothing else.
    op.create_index("ix_products_barcode", "products", ["barcode"])
    op.create_unique_constraint(
        "uix_product_company_barcode", "products", ["company_id", "barcode"]
    )


def downgrade() -> None:
    # Dropped in the reverse order they were made: the constraint and the index
    # both depend on the column, and Postgres refuses to drop it from under them.
    op.drop_constraint("uix_product_company_barcode", "products", type_="unique")
    op.drop_index("ix_products_barcode", table_name="products")
    op.drop_column("products", "barcode")
