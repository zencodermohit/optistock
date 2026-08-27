"""Give a product somewhere to keep a photograph.

A catalogue that reads as a list of names is a spreadsheet. A catalogue with
photographs is a product, and the difference costs one nullable column.

Nullable on purpose, and staying nullable. A product without a picture is a
perfectly ordinary product -- it was entered by someone in a hurry, or it is a
service line, or the photograph has not been taken yet. Making this required
would mean either inventing a placeholder for every such row or refusing to
accept the row at all, and both are worse than an empty cell.

The value is a PATH under the application's own origin, not a remote URL, and
that is deliberate. The obvious thing is to store the supplier's link and let
the browser fetch it, which fails in a way that is invisible in development:
the source CDN for this catalogue answers over http and returns 403 over https,
so on an https page every image is blocked as mixed content. Localhost is http,
so it all looks perfect there. Serving the files ourselves removes the failure,
removes the dependency on somebody else's CDN, and is faster besides.

Revision ID: a7f31c9b02d4
Revises: c4f8a2b61e73
"""

import sqlalchemy as sa
from alembic import op

revision = "a7f31c9b02d4"
down_revision = "c4f8a2b61e73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "image_url",
            sa.String(length=500),
            nullable=True,
            comment="Path to the product photograph, served from this origin.",
        ),
    )


def downgrade() -> None:
    op.drop_column("products", "image_url")
