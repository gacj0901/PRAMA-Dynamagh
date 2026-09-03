"""persistent autonomy policies and runs"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0012_autonomy"
down_revision = "0011_erc8183_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mandates", sa.Column("origin", sa.String(32), nullable=False, server_default="MANUAL"))
    op.add_column("mandates", sa.Column("autonomy_policy_id", sa.String(36), nullable=True))
    op.add_column("mandates", sa.Column("autonomy_run_id", sa.String(36), nullable=True))
    op.create_index("ix_mandates_autonomy_policy_id", "mandates", ["autonomy_policy_id"])
    op.create_index("ix_mandates_autonomy_run_id", "mandates", ["autonomy_run_id"])
    op.create_table("autonomy_policies",
        sa.Column("policy_id", sa.String(36), primary_key=True), sa.Column("name", sa.String(255), nullable=False, unique=True), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("version", sa.String(64), nullable=False), sa.Column("mandate_template", JSONB(), nullable=False), sa.Column("acquisition_mode", sa.String(32), nullable=False), sa.Column("allow_telegraph_http", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("allow_erc8183", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("allow_anchor", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("strict_verification", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("read_only_replay", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("cadence_seconds", sa.Integer(), nullable=False), sa.Column("dedupe_window_seconds", sa.Integer(), nullable=False), sa.Column("max_usdc_per_run", sa.Numeric(18,6), nullable=False), sa.Column("max_usdc_per_day", sa.Numeric(18,6), nullable=False), sa.Column("max_runs_per_day", sa.Integer(), nullable=False), sa.Column("max_concurrent_runs", sa.Integer(), nullable=False), sa.Column("state", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("last_run_at", sa.DateTime(timezone=True)), sa.Column("next_run_at", sa.DateTime(timezone=True)))
    op.create_table("autonomy_runs",
        sa.Column("run_id", sa.String(36), primary_key=True), sa.Column("policy_id", sa.String(36), sa.ForeignKey("autonomy_policies.policy_id", ondelete="CASCADE"), nullable=False), sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False), sa.Column("idempotency_key", sa.String(128), nullable=False), sa.Column("state", sa.String(32), nullable=False), sa.Column("mandate_id", sa.String(36), sa.ForeignKey("mandates.mandate_id")), sa.Column("erc8183_job_id", sa.String(36), sa.ForeignKey("erc8183_jobs.erc8183_job_id")), sa.Column("ticket_id", sa.String(36), sa.ForeignKey("tickets.ticket_id")), sa.Column("planned_cost_usdc", sa.Numeric(18,6), nullable=False), sa.Column("actual_cost_usdc", sa.Numeric(18,6), nullable=False), sa.Column("skip_reason", sa.String(100)), sa.Column("failure_code", sa.String(100)), sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.UniqueConstraint("idempotency_key", name="uq_autonomy_run_idempotency"))
    op.create_index("ix_autonomy_runs_policy_id", "autonomy_runs", ["policy_id"])


def downgrade() -> None:
    op.drop_table("autonomy_runs"); op.drop_table("autonomy_policies")
    op.drop_index("ix_mandates_autonomy_run_id", table_name="mandates"); op.drop_index("ix_mandates_autonomy_policy_id", table_name="mandates")
    op.drop_column("mandates", "autonomy_run_id"); op.drop_column("mandates", "autonomy_policy_id"); op.drop_column("mandates", "origin")
