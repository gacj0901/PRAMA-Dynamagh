"""preserve ERC-8183 chain and cancellation state"""

from alembic import op
import sqlalchemy as sa

revision = "0009_erc8183_recovery_state"
down_revision = "0008_erc8183_funding_receipts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("erc8183_jobs", sa.Column("chain_state", sa.String(32), nullable=True))
    op.add_column("erc8183_jobs", sa.Column("cancel_tx_hash", sa.String(66), nullable=True))
    op.add_column("erc8183_jobs", sa.Column("cancel_block_number", sa.Integer(), nullable=True))
    op.add_column("erc8183_jobs", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("erc8183_jobs", "cancelled_at")
    op.drop_column("erc8183_jobs", "cancel_block_number")
    op.drop_column("erc8183_jobs", "cancel_tx_hash")
    op.drop_column("erc8183_jobs", "chain_state")
