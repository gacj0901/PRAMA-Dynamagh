"""add deterministic ticket-anchor persistence"""

from alembic import op
import sqlalchemy as sa

revision = "0006_anchor_attempt"
down_revision = "0005_ticket"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("block_hash", sa.String(length=66), nullable=True))
    op.create_check_constraint(
        "ck_tickets_anchor_status",
        "tickets",
        "anchor_status IN ('LOCAL_ONLY', 'ANCHOR_PENDING', 'ANCHORED', 'ANCHOR_FAILED')",
    )
    op.create_table(
        "anchor_attempts",
        sa.Column("anchor_attempt_id", sa.String(length=36), primary_key=True),
        sa.Column("ticket_id", sa.String(length=36), sa.ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False),
        sa.Column("chain_id", sa.Integer(), nullable=False),
        sa.Column("contract_address", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("tx_hash", sa.String(length=255), nullable=True),
        sa.Column("block_number", sa.Integer(), nullable=True),
        sa.Column("block_hash", sa.String(length=66), nullable=True),
        sa.Column("failure_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('PENDING', 'SUBMITTED', 'CONFIRMED', 'FAILED')", name="ck_anchor_attempt_status"),
        sa.UniqueConstraint("ticket_id", name="uq_anchor_attempt_ticket"),
    )


def downgrade() -> None:
    op.drop_table("anchor_attempts")
    op.drop_constraint("ck_tickets_anchor_status", "tickets", type_="check")
    op.drop_column("tickets", "block_hash")
