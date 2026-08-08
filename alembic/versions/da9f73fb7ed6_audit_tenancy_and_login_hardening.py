"""audit_tenancy_and_login_hardening

Two unrelated-looking changes that are both about making a security control real
rather than nominal.

1. ``audit_logs.company_id``. Tenant scoping previously ran through an INNER JOIN
   onto ``users``, and ``audit_logs.user_id`` is ON DELETE SET NULL. Deleting a
   user therefore orphaned every audit row they generated and made the whole
   trail invisible to everyone — the opposite of what a compliance record is for.
   Storing the tenant directly on the row keeps history durable and readable
   independently of the actor's lifecycle.

2. ``users.failed_login_attempts`` / ``locked_until``. Backing store for
   account lockout. Without them the login endpoint could be guessed at
   indefinitely; rate limiting alone only slows a single source down.

Revision ID: da9f73fb7ed6
Revises: d168f4adcb13
Create Date: 2026-08-06 11:37:44.297051

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "da9f73fb7ed6"
down_revision: Union[str, None] = "d168f4adcb13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Tenant key directly on the audit row -----------------------------
    # Nullable is not needed: nothing has ever written to this table (the service
    # had no call sites), and the listener only records actions that have an
    # authenticated actor, so a company is always known.
    op.add_column(
        "audit_logs",
        sa.Column("company_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_foreign_key(
        "fk_audit_logs_company_id", "audit_logs", "companies", ["company_id"], ["id"]
    )
    # Supports the router's default query: this tenant's rows, newest first.
    op.create_index(
        "ix_audit_logs_company_timestamp",
        "audit_logs",
        ["company_id", "timestamp"],
    )

    # --- 2. Login lockout counters -------------------------------------------
    op.add_column(
        "users",
        sa.Column(
            "failed_login_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")

    op.drop_index("ix_audit_logs_company_timestamp", table_name="audit_logs")
    op.drop_constraint("fk_audit_logs_company_id", "audit_logs", type_="foreignkey")
    op.drop_column("audit_logs", "company_id")
