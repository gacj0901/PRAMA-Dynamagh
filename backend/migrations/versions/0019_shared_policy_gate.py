"""Add immutable shared policy-gate evaluation records."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0019_shared_policy_gate"
down_revision = "0018_o_epistemic_e1_c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "policy_evaluations",
        sa.Column("policy_evaluation_id", sa.String(length=36), primary_key=True),
        sa.Column("policy_id", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_type", sa.String(length=64), nullable=False),
        sa.Column("policy_subject_type", sa.String(length=64), nullable=False),
        sa.Column("policy_subject_id", sa.String(length=255), nullable=False),
        sa.Column("observation_refs", json_type, nullable=False),
        sa.Column("observation_contract_versions", json_type, nullable=False),
        sa.Column("input_core", json_type, nullable=False),
        sa.Column("input_hash", sa.String(length=66), nullable=False),
        sa.Column("triggered_rule_ids", json_type, nullable=False),
        sa.Column("result", sa.String(length=32), nullable=False),
        sa.Column("result_core", json_type, nullable=False),
        sa.Column("result_hash", sa.String(length=66), nullable=False),
        sa.Column("replay_identity", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "policy_id",
            "policy_version",
            "policy_type",
            "policy_subject_type",
            "policy_subject_id",
            "input_hash",
            name="uq_policy_evaluations_input_identity",
        ),
        sa.UniqueConstraint("replay_identity", name="uq_policy_evaluations_replay_identity"),
    )
    for name, columns in (
        ("ix_policy_evaluations_policy_id", ["policy_id"]),
        ("ix_policy_evaluations_policy_type", ["policy_type"]),
        ("ix_policy_evaluations_policy_subject_id", ["policy_subject_id"]),
        ("ix_policy_evaluations_input_hash", ["input_hash"]),
        ("ix_policy_evaluations_result_hash", ["result_hash"]),
    ):
        op.create_index(name, "policy_evaluations", columns)
    op.execute(
        """
        CREATE FUNCTION reject_policy_evaluation_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'policy evaluation records are append-only: %', TG_OP
                USING ERRCODE = '55000';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER policy_evaluations_immutable_update
        BEFORE UPDATE OR DELETE ON policy_evaluations
        FOR EACH ROW EXECUTE FUNCTION reject_policy_evaluation_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS policy_evaluations_immutable_update ON policy_evaluations")
    op.execute("DROP FUNCTION IF EXISTS reject_policy_evaluation_mutation()")
    for name in (
        "ix_policy_evaluations_policy_id",
        "ix_policy_evaluations_policy_type",
        "ix_policy_evaluations_policy_subject_id",
        "ix_policy_evaluations_input_hash",
        "ix_policy_evaluations_result_hash",
    ):
        op.drop_index(name, table_name="policy_evaluations")
    op.drop_table("policy_evaluations")
