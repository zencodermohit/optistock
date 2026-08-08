"""Index inventory_movements.reference_id for scan de-duplication.

Revision ID: d2b8f5a71c04
Revises: c1e4a7b92f30

The scan ingest endpoint looks a movement up by reference_id on every request,
to make a retried scan a no-op instead of a second deduction. Unindexed, that is
a sequential scan of the whole ledger per scan -- on a table that only ever
grows, and from a device that may fire several times a second on a busy dock.

Partial, because only scans set this column. The great majority of movements
come from sales and carry a sale id there, and none of them are ever looked up
this way; excluding them keeps the index proportional to the traffic that
actually queries it.
"""

from alembic import op

revision = "d2b8f5a71c04"
down_revision = "c1e4a7b92f30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX ix_inventory_movements_scan_reference
        ON inventory_movements (reference_id)
        WHERE reference_id LIKE 'scan:%'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_inventory_movements_scan_reference")
