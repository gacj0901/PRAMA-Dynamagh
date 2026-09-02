"""add mandate execution state

Revision ID: 0001_mandate_state
Revises:
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_mandate_state"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mandates",
        sa.Column("mandate_id", sa.String(length=36), primary_key=True),
        sa.Column("actor_id", sa.String(length=255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("mandate_type", sa.String(length=100), nullable=False),
        sa.Column("constraints", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_budget_usdc", sa.Numeric(precision=18, scale=6), nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "acquisition_tasks",
        sa.Column("acquisition_id", sa.String(length=36), primary_key=True),
        sa.Column("mandate_id", sa.String(length=36), sa.ForeignKey("mandates.mandate_id", ondelete="CASCADE"), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("requested_intent", sa.String(length=255), nullable=True),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("telegraph_job_id", sa.String(length=255), nullable=True),
        sa.Column("intent_id", sa.String(length=255), nullable=True),
        sa.Column("callback_address", sa.String(length=255), nullable=True),
        sa.Column("tx_hash", sa.String(length=255), nullable=True),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("onchain_output_hash", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_acquisition_tasks_mandate_id", "acquisition_tasks", ["mandate_id"])
    op.create_table(
        "mandate_transitions",
        sa.Column("transition_id", sa.String(length=36), primary_key=True),
        sa.Column("mandate_id", sa.String(length=36), sa.ForeignKey("mandates.mandate_id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mandate_transitions_mandate_id", "mandate_transitions", ["mandate_id"])


def downgrade() -> None:
    op.drop_table("mandate_transitions")
    op.drop_table("acquisition_tasks")
    op.drop_table("mandates")

