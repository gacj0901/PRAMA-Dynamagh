"""evidence decision"""
from alembic import op
revision="0003_evidence_decision"; down_revision="0002_acquisition_provenance"; branch_labels=None; depends_on=None
def upgrade():
    op.execute("CREATE TABLE evidence (evidence_id varchar(36) PRIMARY KEY, mandate_id varchar(36), acquisition_id varchar(36), telegraph_call_id varchar(36) UNIQUE, evidence_type varchar(64), source_kind varchar(32), source_intent varchar(255), source_miner_id varchar(255), source_signal_hash varchar(255), normalized_payload jsonb, content_hash varchar(66), normalizer_version varchar(64), provenance_status varchar(32), admissibility varchar(32), limitation_codes jsonb, created_at timestamptz, updated_at timestamptz)")
    op.execute("CREATE TABLE structural_evaluations (evaluation_id varchar(36) PRIMARY KEY, mandate_id varchar(36), evaluator varchar(64), evaluator_version varchar(64), evidence_set_hash varchar(66), admitted_evidence_ids jsonb, limited_evidence_ids jsonb, rejected_evidence_ids jsonb, limitation_codes jsonb, contradiction_codes jsonb, structural_state varchar(64), evaluation_payload jsonb, created_at timestamptz, completed_at timestamptz)")
    op.execute("CREATE TABLE decisions (decision_id varchar(36) PRIMARY KEY, mandate_id varchar(36), evaluation_id varchar(36) UNIQUE, state varchar(16), policy_version varchar(64), evidence_set_hash varchar(66), reason_codes jsonb, decision_payload jsonb, created_at timestamptz, completed_at timestamptz)")
def downgrade(): op.execute("DROP TABLE decisions");op.execute("DROP TABLE structural_evaluations");op.execute("DROP TABLE evidence")
