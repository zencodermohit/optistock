"""Assistant proposed actions

Where the assistant's suggested writes wait for a human. The two payload
columns are the point: proposed_payload is what the model asked for and
executed_payload is what the approver actually ran, kept apart so an amended
quantity stays visible instead of overwriting the suggestion.

Revision ID: f4a2c8b91d70
Revises: e3c7a94b18d5
Create Date: 2026-08-09

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f4a2c8b91d70"
down_revision = "e3c7a94b18d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("company_id", sa.UUID(), nullable=False),
        sa.Column("action_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("proposed_payload", postgresql.JSONB(), nullable=False),
        sa.Column("executed_payload", postgresql.JSONB(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("source_question", sa.Text(), nullable=True),
        sa.Column("proposed_by_model", sa.String(length=100), nullable=True),
        sa.Column("requested_by_user_id", sa.UUID(), nullable=True),
        sa.Column("decided_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        # SET NULL rather than CASCADE on both user references: deleting a user
        # must not delete the record that they approved something.
        sa.ForeignKeyConstraint(
            ["requested_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assistant_actions_company_id", "assistant_actions", ["company_id"]
    )
    # The approvals screen's only query: this company's proposals, newest first,
    # usually filtered to those still awaiting a decision.
    op.create_index(
        "ix_assistant_actions_company_status",
        "assistant_actions",
        ["company_id", "status", "proposed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assistant_actions_company_status", table_name="assistant_actions")
    op.drop_index("ix_assistant_actions_company_id", table_name="assistant_actions")
    op.drop_table("assistant_actions")
