"""Record provider, access mechanism and payment rail independently."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0028_acquisition_access_plane"
down_revision = "0027_cold_start_bootstrap"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("acquisition_tasks", "telegraph_calls"):
        op.add_column(table, sa.Column("resource_provider", sa.String(64), nullable=True))
        op.add_column(table, sa.Column("access_mechanism", sa.String(32), nullable=True))
        op.add_column(table, sa.Column("payment_rail", sa.String(32), nullable=True))
    op.add_column("acquisition_tasks", sa.Column("resource_metadata", JSONB, nullable=True))


def downgrade():
    # Existing call/task provenance is part of the audit surface; removing it
    # would make replay less attributable.  Keep migrations append-only.
    raise RuntimeError("Acquisition access-plane history is append-only; destructive downgrade forbidden")
