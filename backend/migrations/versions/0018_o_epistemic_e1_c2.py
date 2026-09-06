"""Add immutable O_EPISTEMIC E1-C2 relational evaluation artifacts."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0018_o_epistemic_e1_c2"
down_revision = "0017_o_epistemic_e1_c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "evidence_relations",
        sa.Column("relation_id", sa.String(length=36), primary_key=True),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("requirement_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_id", sa.String(length=36), nullable=False),
        sa.Column("relation_state", sa.String(length=32), nullable=False),
        sa.Column("relation_basis", json_type, nullable=False),
        sa.Column("observer_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("canonical_hash", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["target_id"], ["epistemic_targets.target_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requirement_id"], ["evidence_requirements.requirement_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.evidence_id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "target_id",
            "requirement_id",
            "evidence_id",
            "observer_version",
            "contract_version",
            name="uq_evidence_relations_lineage_version",
        ),
        sa.CheckConstraint(
            "relation_state IN ('SATISFIES', 'CONTRADICTS', 'UNRESOLVED', 'NOT_APPLICABLE')",
            name="ck_evidence_relations_state",
        ),
    )
    op.create_index("ix_evidence_relations_target_id", "evidence_relations", ["target_id"])
    op.create_index("ix_evidence_relations_requirement_id", "evidence_relations", ["requirement_id"])
    op.create_index("ix_evidence_relations_evidence_id", "evidence_relations", ["evidence_id"])
    op.create_index("ix_evidence_relations_canonical_hash", "evidence_relations", ["canonical_hash"])

    op.create_table(
        "epistemic_evaluations",
        sa.Column("evaluation_id", sa.String(length=36), primary_key=True),
        sa.Column("mandate_id", sa.String(length=36), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("evidence_set_hash", sa.String(length=66), nullable=False),
        sa.Column("requirement_states", json_type, nullable=False),
        sa.Column("relations", json_type, nullable=False),
        sa.Column("contradictions", json_type, nullable=False),
        sa.Column("limitations", json_type, nullable=False),
        sa.Column("structural_state", sa.String(length=32), nullable=False),
        sa.Column("observer_version", sa.String(length=64), nullable=False),
        sa.Column("contract_version", sa.String(length=64), nullable=False),
        sa.Column("algorithm_version", sa.String(length=64), nullable=False),
        sa.Column("source_evidence_ids", json_type, nullable=False),
        sa.Column("canonical_hash", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["mandate_id"], ["mandates.mandate_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_id"], ["epistemic_targets.target_id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "structural_state IN ('COMPLETE', 'INCOMPLETE', 'CONTRADICTED')",
            name="ck_epistemic_evaluations_structural_state",
        ),
    )
    op.create_index("ix_epistemic_evaluations_mandate_id", "epistemic_evaluations", ["mandate_id"])
    op.create_index("ix_epistemic_evaluations_target_id", "epistemic_evaluations", ["target_id"])
    op.create_index("ix_epistemic_evaluations_evidence_set_hash", "epistemic_evaluations", ["evidence_set_hash"])
    op.create_index("ix_epistemic_evaluations_canonical_hash", "epistemic_evaluations", ["canonical_hash"])

    op.execute(
        """
        CREATE FUNCTION reject_e1_c2_immutable_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'E1-C2 immutable table cannot be updated: %', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in ("evidence_relations", "epistemic_evaluations"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_immutable_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION reject_e1_c2_immutable_update();
            """
        )


def downgrade() -> None:
    for table in ("evidence_relations", "epistemic_evaluations"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable_update ON {table}")
    op.execute("DROP FUNCTION IF EXISTS reject_e1_c2_immutable_update()")
    op.drop_table("evidence_relations")
    op.drop_table("epistemic_evaluations")
