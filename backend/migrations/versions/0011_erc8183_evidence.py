"""link Evidence to certified ERC-8183 provenance"""

from alembic import op
import sqlalchemy as sa

revision = "0011_erc8183_evidence"
down_revision = "0010_callback_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence", sa.Column("erc8183_job_id", sa.String(36), nullable=True))
    op.create_foreign_key("fk_evidence_erc8183_job", "evidence", "erc8183_jobs", ["erc8183_job_id"], ["erc8183_job_id"])
    op.create_unique_constraint("uq_evidence_erc8183_job_normalizer", "evidence", ["erc8183_job_id", "normalizer_version"])


def downgrade() -> None:
    op.drop_constraint("uq_evidence_erc8183_job_normalizer", "evidence")
    op.drop_constraint("fk_evidence_erc8183_job", "evidence", type_="foreignkey")
    op.drop_column("evidence", "erc8183_job_id")
