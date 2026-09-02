"""persist Telegraph ERC-8183 jobs

Revision ID: 0007_erc8183_jobs
Revises: 0006_anchor_attempt
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007_erc8183_jobs"
down_revision = "0006_anchor_attempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("usage_events", "mandate_id", existing_type=sa.String(length=36), nullable=True)
    op.create_table(
        "erc8183_jobs",
        sa.Column("erc8183_job_id", sa.String(36), primary_key=True),
        sa.Column("mandate_id", sa.String(36), sa.ForeignKey("mandates.mandate_id"), nullable=True),
        sa.Column("ticket_id", sa.String(36), sa.ForeignKey("tickets.ticket_id"), nullable=True),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("diamond_address", sa.String(42), nullable=False),
        sa.Column("telegraph_job_id", sa.String(78), nullable=True),
        sa.Column("intent_name", sa.String(64), nullable=False),
        sa.Column("intent_id", sa.String(66), nullable=False),
        sa.Column("callback_address", sa.String(42), nullable=False),
        sa.Column("params_payload", postgresql.JSONB(), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("budget_usdc", sa.Numeric(18, 6), nullable=True),
        sa.Column("miner_payment_usdc", sa.Numeric(18, 6), nullable=True),
        sa.Column("protocol_fee_usdc", sa.Numeric(18, 6), nullable=True),
        sa.Column("output_hash", sa.String(66), nullable=True),
        sa.Column("create_tx_hash", sa.String(66), nullable=True),
        sa.Column("create_block_number", sa.Integer(), nullable=True),
        sa.Column("terminal_tx_hash", sa.String(66), nullable=True),
        sa.Column("terminal_block_number", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("state IN ('PREPARING','ESCROW_READY','SUBMITTED','FUNDED','TERMINAL','CANCEL_PENDING','CANCELLED','FAILED')", name="ck_erc8183_job_state"),
        sa.UniqueConstraint("chain_id", "diamond_address", "telegraph_job_id", name="uq_erc8183_chain_diamond_job"),
    )
    op.create_index("ix_erc8183_jobs_mandate_id", "erc8183_jobs", ["mandate_id"])
    op.create_index("ix_erc8183_jobs_ticket_id", "erc8183_jobs", ["ticket_id"])


def downgrade() -> None:
    op.drop_table("erc8183_jobs")
    op.alter_column("usage_events", "mandate_id", existing_type=sa.String(length=36), nullable=False)
