"""Add immutable O_EPISTEMIC E1-C1 domain contracts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0017_o_epistemic_e1_c1"
down_revision = "0016_o_evidence_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "epistemic_targets",
        sa.Column("target_id", sa.String(length=36), primary_key=True),
        sa.Column("mandate_id", sa.String(length=36), nullable=False),
        sa.Column("target_type", sa.String(length=100), nullable=False),
        sa.Column("parameters", json_type, nullable=False),
        sa.Column("temporal_scope", json_type, nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("canonical_hash", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.mandate_id"], ondelete="CASCADE"),
    )
    op.create_index("ix_epistemic_targets_mandate_id", "epistemic_targets", ["mandate_id"])
    op.create_index("ix_epistemic_targets_canonical_hash", "epistemic_targets", ["canonical_hash"])

    op.create_table(
        "evidence_requirements",
        sa.Column("requirement_id", sa.String(length=36), primary_key=True),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_type", sa.String(length=64), nullable=False),
        sa.Column("parameters", json_type, nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("canonical_hash", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["epistemic_targets.target_id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "target_id",
            "requirement_type",
            "contract_version",
            name="uq_evidence_requirements_target_type_version",
        ),
        sa.CheckConstraint(
            "requirement_type IN ('asset_identity', 'quote_currency', 'price_value', 'temporal_applicability')",
            name="ck_evidence_requirements_crypto_price_v01_type",
        ),
    )
    op.create_index("ix_evidence_requirements_target_id", "evidence_requirements", ["target_id"])
    op.create_index("ix_evidence_requirements_canonical_hash", "evidence_requirements", ["canonical_hash"])

    op.create_table(
        "crypto_price_evidence",
        sa.Column("crypto_price_evidence_id", sa.String(length=36), primary_key=True),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("asset", sa.String(length=128), nullable=False),
        sa.Column("quote_currency", sa.String(length=32), nullable=False),
        sa.Column("price_value", sa.Numeric(precision=38, scale=18), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("canonical_hash", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.evidence_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("evidence_id", name="uq_crypto_price_evidence_evidence_id"),
    )
    op.create_index("ix_crypto_price_evidence_evidence_id", "crypto_price_evidence", ["evidence_id"])
    op.create_index("ix_crypto_price_evidence_canonical_hash", "crypto_price_evidence", ["canonical_hash"])

    op.execute(
        """
        CREATE FUNCTION reject_e1_c1_immutable_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'E1-C1 immutable table cannot be updated: %', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("epistemic_targets", "evidence_requirements", "crypto_price_evidence"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_immutable_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_e1_c1_immutable_update();
            """
        )


def downgrade() -> None:
    for table in ("crypto_price_evidence", "evidence_requirements", "epistemic_targets"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_update ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_e1_c1_immutable_update()")
    op.drop_table("crypto_price_evidence")
    op.drop_table("evidence_requirements")
    op.drop_table("epistemic_targets")
