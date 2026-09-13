"""Epistemic requirement registry validation drops the crypto-only SQL constraint."""
from alembic import op
import sqlalchemy as sa

revision = "0025_epistemic_registry"
down_revision = "0024_unlimited_agent_authority"
branch_labels = None
depends_on = None

CONSTRAINT = "ck_evidence_requirements_crypto_price_v01_type"


def upgrade():
    op.drop_constraint(CONSTRAINT, "evidence_requirements", type_="check")


def downgrade():
    raise RuntimeError("Epistemic requirement history is append-only; destructive downgrade forbidden")
