"""g4 uniqueness"""
from alembic import op
revision="0004_g4_uniqueness"; down_revision="0003_evidence_decision"; branch_labels=None; depends_on=None
def upgrade():
    op.create_unique_constraint("uq_evidence_call_normalizer","evidence",["telegraph_call_id","normalizer_version"])
    op.create_unique_constraint("uq_evaluation_input","structural_evaluations",["mandate_id","evaluator_version","evidence_set_hash"])
    op.create_unique_constraint("uq_decision_evaluation_policy","decisions",["evaluation_id","policy_version"])
def downgrade():
    op.drop_constraint("uq_decision_evaluation_policy","decisions");op.drop_constraint("uq_evaluation_input","structural_evaluations");op.drop_constraint("uq_evidence_call_normalizer","evidence")
