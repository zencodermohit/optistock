"""event_backbone_alerts_forecast_runs

Schema for the event-driven pivot. Three new tables plus one column, all added
in one migration so weeks 2-7 are pure application code with no schema churn.

1. ``event_outbox`` — every state change, written in the SAME transaction as the
   change itself. This is the transactional outbox pattern. Publishing straight
   to a queue from inside a request is a "dual write": if the process dies
   between the commit and the publish, the database has the change and the event
   never fires — silently, with nothing to retry. Writing the event to a table in
   the same transaction makes it atomic; a separate relay publishes it.

2. ``alerts`` — low stock, overdue purchase orders, anomalies. The partial unique
   index is the important part: at most ONE open alert per subject per type, so a
   condition that keeps re-firing updates a single row instead of producing a
   thousand duplicates.

3. ``forecast_runs`` — every prediction is stored with the window it covers, so
   actuals can be filled in later and accuracy (MAPE) measured. Without this, a
   forecast is an assertion; with it, it is a measurable claim.

4. ``inventory.reorder_point`` — placed on inventory rather than products because
   (product, warehouse) is the grain at which "am I low on stock?" is actually
   evaluated. A busy warehouse needs a different buffer than a quiet one.

Revision ID: c1e4a7b92f30
Revises: da9f73fb7ed6
Create Date: 2026-08-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c1e4a7b92f30"
down_revision: Union[str, None] = "da9f73fb7ed6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Transactional outbox
    # ------------------------------------------------------------------ #
    op.create_table(
        "event_outbox",
        # BIGSERIAL gives a gap-free total order, which is what a replay needs.
        # A UUID primary key would not be sortable by insertion order.
        sa.Column("sequence", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=50), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        # JSONB rather than JSON: binary storage, and it can be indexed and
        # queried. The older tables here use JSON; new ones should not.
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # NULL means "not yet relayed". This single nullable column is the whole
        # publish state machine.
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("sequence"),
        sa.UniqueConstraint("event_id", name="uq_event_outbox_event_id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
    )

    # PARTIAL index — indexes only unpublished rows. The table grows forever, but
    # this index stays roughly the size of the backlog, so the relay's
    # "give me the next unpublished events" query stays fast no matter how many
    # million rows have already been published.
    op.execute(
        "CREATE INDEX ix_event_outbox_unpublished ON event_outbox (sequence) "
        "WHERE published_at IS NULL"
    )
    # Replay/debug: "show me everything that happened to this inventory row".
    op.create_index(
        "ix_event_outbox_aggregate",
        "event_outbox",
        ["aggregate_type", "aggregate_id"],
    )
    op.create_index(
        "ix_event_outbox_company_occurred",
        "event_outbox",
        ["company_id", "occurred_at"],
    )

    # ------------------------------------------------------------------ #
    # 2. Alerts
    # ------------------------------------------------------------------ #
    op.create_table(
        "alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alert_type", sa.String(length=50), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="open"
        ),
        # What the alert is about, e.g. ("inventory", <inventory row id>).
        sa.Column("subject_type", sa.String(length=50), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        # The evidence that fired it — same explainability contract as
        # Recommendation.evidence. The UI renders this, so an alert can always
        # answer "why am I seeing this?".
        sa.Column("detail", postgresql.JSONB(), nullable=False),
        # Provenance back to the event that caused it.
        sa.Column("triggered_by_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["dismissed_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('open', 'resolved', 'dismissed')", name="ck_alerts_status"
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'critical')", name="ck_alerts_severity"
        ),
    )

    # De-duplication, enforced by the database rather than by remembering to
    # check. Only ONE alert may be open per (company, type, subject) at a time —
    # a stock level that stays low for a week produces one alert, not one per
    # event. Resolved and dismissed rows are excluded, so the same alert can
    # legitimately re-open later.
    op.execute(
        "CREATE UNIQUE INDEX uq_alerts_one_open_per_subject ON alerts "
        "(company_id, alert_type, subject_type, subject_id) WHERE status = 'open'"
    )
    op.create_index(
        "ix_alerts_company_status_created",
        "alerts",
        ["company_id", "status", "created_at"],
    )

    # ------------------------------------------------------------------ #
    # 3. Forecast runs (accuracy tracking)
    # ------------------------------------------------------------------ #
    op.create_table(
        "forecast_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        # What was predicted, and over what window.
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("forecast_quantity", sa.Integer(), nullable=False),
        sa.Column("avg_daily_sales", sa.Numeric(12, 4), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("predicted_at", sa.DateTime(timezone=True), nullable=False),
        # The date the forecast window closes. Until this passes there is
        # nothing to compare against.
        sa.Column("horizon_end", sa.Date(), nullable=False),
        # Filled in after the window closes.
        sa.Column("actual_quantity", sa.Integer(), nullable=True),
        sa.Column("absolute_error", sa.Integer(), nullable=True),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"]),
    )

    # Partial index again: the scoring job only ever asks for forecasts whose
    # window has closed but which have not been scored yet.
    op.execute(
        "CREATE INDEX ix_forecast_runs_unscored ON forecast_runs (horizon_end) "
        "WHERE scored_at IS NULL"
    )
    op.create_index(
        "ix_forecast_runs_company_predicted",
        "forecast_runs",
        ["company_id", "predicted_at"],
    )

    # ------------------------------------------------------------------ #
    # 4. Reorder point, at the (product, warehouse) grain
    # ------------------------------------------------------------------ #
    # Default 0 means "no threshold configured" and therefore "never alert".
    # Opt-in by default: no alert noise until somebody sets a real number.
    op.add_column(
        "inventory",
        sa.Column(
            "reorder_point",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_inventory_reorder_point_non_negative", "inventory", "reorder_point >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_inventory_reorder_point_non_negative", "inventory", type_="check"
    )
    op.drop_column("inventory", "reorder_point")

    op.drop_index("ix_forecast_runs_company_predicted", table_name="forecast_runs")
    op.execute("DROP INDEX IF EXISTS ix_forecast_runs_unscored")
    op.drop_table("forecast_runs")

    op.drop_index("ix_alerts_company_status_created", table_name="alerts")
    op.execute("DROP INDEX IF EXISTS uq_alerts_one_open_per_subject")
    op.drop_table("alerts")

    op.drop_index("ix_event_outbox_company_occurred", table_name="event_outbox")
    op.drop_index("ix_event_outbox_aggregate", table_name="event_outbox")
    op.execute("DROP INDEX IF EXISTS ix_event_outbox_unpublished")
    op.drop_table("event_outbox")
