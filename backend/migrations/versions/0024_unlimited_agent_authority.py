"""Explicit unlimited authority grants and nullable absent principal binding."""
from alembic import op
import sqlalchemy as sa

revision = "0024_unlimited_agent_authority"
down_revision = "0023_authority_profile_v0"
branch_labels = None
depends_on = None


def upgrade():
    table = "agent_authority_profiles"
    op.add_column(table, sa.Column("unlimited_budget", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(table, sa.Column("unlimited_execution_rate", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("execution_permits", "principal_id", nullable=True)


def downgrade():
    raise RuntimeError("Authority history is append-only; destructive downgrade forbidden")
