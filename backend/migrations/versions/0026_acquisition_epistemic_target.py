"""AcquisitionTask gains precommited epistemic target identity fields."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0026_acquisition_epistemic_target"
down_revision = "0025_epistemic_registry_requirements"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("acquisition_tasks", sa.Column("target_subject", sa.String(255), nullable=True))
    op.add_column("acquisition_tasks", sa.Column("target_property", sa.String(255), nullable=True))
    op.add_column("acquisition_tasks", sa.Column("target_unit", sa.String(64), nullable=True))
    op.add_column("acquisition_tasks", sa.Column("temporal_scope", JSONB, nullable=True))
    op.add_column("acquisition_tasks", sa.Column("target_constraints", JSONB, nullable=True))
    op.add_column("acquisition_tasks", sa.Column("target_schema_version", sa.String(64), nullable=True))


def downgrade():
    raise RuntimeError("Acquisition target history is append-only; destructive downgrade forbidden")
