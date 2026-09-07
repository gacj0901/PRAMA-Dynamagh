"""Delegated authority profiles and single-use execution permits."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0022_delegated_autonomy"
down_revision = "0021_titular_disclosure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_identities", sa.Column("autonomy_state", sa.String(32), nullable=False, server_default="ACTIVE"))
    op.create_table("agent_authority_profiles",
        sa.Column("authority_profile_id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(255), nullable=False),
        sa.Column("agent_identity_id", sa.String(255), sa.ForeignKey("agent_identities.agent_id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("allowed_intents", JSONB(), nullable=False),
        sa.Column("allowed_action_kinds", JSONB(), nullable=False),
        sa.Column("economic_budget", sa.Numeric(18, 6)),
        sa.Column("per_action_budget", sa.Numeric(18, 6)),
        sa.Column("rolling_budget", JSONB()),
        sa.Column("concurrency_limit", sa.Integer()),
        sa.Column("cadence_policy", JSONB()),
        sa.Column("external_execution_allowed", sa.Boolean(), nullable=False),
        sa.Column("telegraph_allowed", sa.Boolean(), nullable=False),
        sa.Column("anchoring_allowed", sa.Boolean(), nullable=False),
        sa.Column("erc8183_allowed", sa.Boolean(), nullable=False),
        sa.Column("human_review_thresholds", JSONB(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_authority_profiles_agent", "agent_authority_profiles", ["agent_identity_id"])
    op.create_table("execution_permits",
        sa.Column("permit_id", sa.String(36), primary_key=True),
        sa.Column("principal_id", sa.String(255), nullable=False),
        sa.Column("agent_identity_id", sa.String(255), sa.ForeignKey("agent_identities.agent_id"), nullable=False),
        sa.Column("mandate_id", sa.String(36), sa.ForeignKey("mandates.mandate_id"), nullable=False),
        sa.Column("action_id", sa.String(255), nullable=False, unique=True),
        sa.Column("action_kind", sa.String(64), nullable=False),
        sa.Column("authority_profile_id", sa.String(36), sa.ForeignKey("agent_authority_profiles.authority_profile_id"), nullable=False),
        sa.Column("g12_result", sa.String(32), nullable=False),
        sa.Column("g13_result", sa.String(32), nullable=False),
        sa.Column("decision_id", sa.String(36)),
        sa.Column("constraints", JSONB(), nullable=False),
        sa.Column("authority_hash", sa.String(66), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("result_hash", sa.String(66)),
    )
    op.create_index("ix_execution_permits_agent", "execution_permits", ["agent_identity_id"])
    op.execute("""
      CREATE FUNCTION reject_authority_profile_mutation() RETURNS trigger AS $$
      BEGIN RAISE EXCEPTION 'authority profiles are immutable; create a new version'; END;
      $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER authority_profile_immutable BEFORE UPDATE OR DELETE ON agent_authority_profiles FOR EACH ROW EXECUTE FUNCTION reject_authority_profile_mutation()")
    op.execute("""
      CREATE FUNCTION guard_execution_permit_mutation() RETURNS trigger AS $$
      BEGIN
        IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'execution permits are immutable'; END IF;
        IF OLD.consumed_at IS NOT NULL OR NEW.permit_id IS DISTINCT FROM OLD.permit_id
           OR NEW.authority_hash IS DISTINCT FROM OLD.authority_hash
           OR NEW.agent_identity_id IS DISTINCT FROM OLD.agent_identity_id
           OR NEW.action_id IS DISTINCT FROM OLD.action_id
           OR NEW.mandate_id IS DISTINCT FROM OLD.mandate_id
           OR NEW.principal_id IS DISTINCT FROM OLD.principal_id
           OR NEW.action_kind IS DISTINCT FROM OLD.action_kind
           OR NEW.authority_profile_id IS DISTINCT FROM OLD.authority_profile_id
           OR NEW.g12_result IS DISTINCT FROM OLD.g12_result
           OR NEW.g13_result IS DISTINCT FROM OLD.g13_result
           OR NEW.decision_id IS DISTINCT FROM OLD.decision_id
           OR NEW.constraints IS DISTINCT FROM OLD.constraints
           OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
           OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
           OR (NEW.result_hash IS DISTINCT FROM OLD.result_hash AND NEW.consumed_at IS NULL) THEN
          RAISE EXCEPTION 'execution permit mutation is immutable';
        END IF;
        IF NEW.consumed_at IS NULL THEN
          RAISE EXCEPTION 'execution permit can only transition to consumed';
        END IF;
        RETURN NEW;
      END;
      $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER execution_permit_single_use BEFORE UPDATE OR DELETE ON execution_permits FOR EACH ROW EXECUTE FUNCTION guard_execution_permit_mutation()")
    op.execute("""
      CREATE FUNCTION reject_audit_event_mutation() RETURNS trigger AS $$
      BEGIN
        IF (OLD.metadata->>'append_only') = 'true' THEN
          RAISE EXCEPTION 'audit event is append-only';
        END IF;
        RETURN OLD;
      END;
      $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER audit_event_immutable BEFORE UPDATE OR DELETE ON usage_events FOR EACH ROW EXECUTE FUNCTION reject_audit_event_mutation()")


def downgrade() -> None:
    raise RuntimeError("Delegated autonomy history is append-only; no destructive downgrade")
