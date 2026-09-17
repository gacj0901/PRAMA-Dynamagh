"""Add explicit bounded cold-start authority grants."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0027_cold_start_bootstrap"
down_revision = "0026_acq_epistemic_target"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "bootstrap_authorities",
        sa.Column("bootstrap_authority_id", sa.String(36), primary_key=True),
        sa.Column("agent_identity_id", sa.String(255), sa.ForeignKey("agent_identities.agent_id"), nullable=False),
        sa.Column("authority_profile_id", sa.String(36), sa.ForeignKey("agent_authority_profiles.authority_profile_id"), nullable=False),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("autonomy_policies.policy_id"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("status", sa.String(16), nullable=False, server_default="ACTIVE"),
        sa.Column("max_actions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("consumed_actions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_spend_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("allowed_action_kinds", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("authority_hash", sa.String(66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("max_actions > 0", name="ck_bootstrap_max_actions"),
        sa.CheckConstraint("consumed_actions >= 0 AND consumed_actions <= max_actions", name="ck_bootstrap_consumed_actions"),
        sa.CheckConstraint("max_spend_usdc >= 0", name="ck_bootstrap_max_spend"),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED', 'EXHAUSTED')", name="ck_bootstrap_status"),
    )
    op.create_index("ix_bootstrap_authorities_agent_identity_id", "bootstrap_authorities", ["agent_identity_id"])
    op.create_index("ix_bootstrap_authorities_authority_profile_id", "bootstrap_authorities", ["authority_profile_id"])
    op.create_index("ix_bootstrap_authorities_policy_id", "bootstrap_authorities", ["policy_id"])
    op.create_index("ix_bootstrap_authorities_status", "bootstrap_authorities", ["status"])


def downgrade():
    raise RuntimeError("Bootstrap authority history is append-only; destructive downgrade forbidden")
