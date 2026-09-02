"""persist bounded ERC-8183 escrow funding receipts"""

from alembic import op
import sqlalchemy as sa

revision = "0008_erc8183_funding_receipts"
down_revision = "0007_erc8183_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("erc8183_jobs", sa.Column("approval_tx_hash", sa.String(66), nullable=True))
    op.add_column("erc8183_jobs", sa.Column("approval_block_number", sa.Integer(), nullable=True))
    op.add_column("erc8183_jobs", sa.Column("deposit_tx_hash", sa.String(66), nullable=True))
    op.add_column("erc8183_jobs", sa.Column("deposit_block_number", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("erc8183_jobs", "deposit_block_number")
    op.drop_column("erc8183_jobs", "deposit_tx_hash")
    op.drop_column("erc8183_jobs", "approval_block_number")
    op.drop_column("erc8183_jobs", "approval_tx_hash")
