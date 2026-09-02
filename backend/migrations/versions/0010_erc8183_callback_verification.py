"""persist ERC-8183 callback verification evidence"""

from alembic import op
import sqlalchemy as sa

revision = "0010_callback_verification"
down_revision = "0009_erc8183_recovery_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("erc8183_jobs", sa.Column("callback_response_hash", sa.String(66), nullable=True))
    op.add_column("erc8183_jobs", sa.Column("callback_verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("erc8183_jobs", sa.Column("callback_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("erc8183_jobs", "callback_verified", server_default=None)


def downgrade() -> None:
    op.drop_column("erc8183_jobs", "callback_verified_at")
    op.drop_column("erc8183_jobs", "callback_verified")
    op.drop_column("erc8183_jobs", "callback_response_hash")
