"""Versioned authority metadata and immutable lifecycle, without runtime rollout."""
from alembic import op
import sqlalchemy as sa

revision = "0023_authority_profile_v0"
down_revision = "0022_delegated_autonomy"
branch_labels = None
depends_on = None


def upgrade():
    table = "agent_authority_profiles"
    op.add_column(table, sa.Column("version", sa.Integer(), nullable=True))
    # The 0022 grant and its references are preserved byte-for-byte. Only new
    # version metadata is assigned deterministically; no principal/actor invented.
    op.execute("ALTER TABLE agent_authority_profiles DISABLE TRIGGER authority_profile_immutable")
    op.execute("""
        WITH numbered AS (
            SELECT authority_profile_id, row_number() OVER (
                PARTITION BY agent_identity_id ORDER BY created_at, authority_profile_id
            ) AS version FROM agent_authority_profiles
        ) UPDATE agent_authority_profiles p SET version = n.version
          FROM numbered n WHERE p.authority_profile_id = n.authority_profile_id
    """)
    op.execute("ALTER TABLE agent_authority_profiles ENABLE TRIGGER authority_profile_immutable")
    op.alter_column(table, "version", nullable=False)
    op.alter_column(table, "principal_id", nullable=True)
    for name in ("rolling_budget_usdc", "review_required_above_usdc"):
        op.add_column(table, sa.Column(name, sa.Numeric(18, 6), nullable=True))
    for name in ("rolling_window_seconds", "cadence_seconds", "max_executions_per_window", "execution_window_seconds"):
        op.add_column(table, sa.Column(name, sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("created_by", sa.String(255), nullable=True))
    # Legacy grants are not retroactively attested. The new resolver rejects an
    # absent hash; operators must explicitly create a reviewed v0 version.
    op.add_column(table, sa.Column("authority_hash", sa.String(66), nullable=True))
    op.create_unique_constraint("uq_authority_agent_version", table, ["agent_identity_id", "version"])
    op.create_index("ix_agent_authority_profiles_status", table, ["status"])
    for name, sql in (
        ("ck_authority_version", "version > 0"),
        ("ck_authority_status", "status IN ('ACTIVE', 'SUSPENDED', 'REVOKED', 'EXPIRED')"),
        ("ck_authority_validity", "valid_until IS NULL OR valid_until > valid_from"),
        ("ck_authority_budgets", "COALESCE(economic_budget >= 0, true) AND COALESCE(per_action_budget >= 0, true) AND COALESCE(rolling_budget_usdc >= 0, true) AND COALESCE(review_required_above_usdc >= 0, true)"),
        ("ck_authority_windows", "COALESCE(concurrency_limit > 0, true) AND COALESCE(cadence_seconds >= 0, true) AND COALESCE(rolling_window_seconds > 0, true) AND COALESCE(execution_window_seconds > 0, true) AND COALESCE(max_executions_per_window > 0, true)"),
    ):
        op.create_check_constraint(name, table, sql)
    op.create_table("authority_profile_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("authority_profile_id", sa.String(36), sa.ForeignKey("agent_authority_profiles.authority_profile_id"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("authority_hash", sa.String(66), nullable=False),
        sa.UniqueConstraint("authority_profile_id", "sequence", name="uq_authority_event_sequence"),
        sa.CheckConstraint("sequence > 0", name="ck_authority_event_sequence"),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUSPENDED', 'REVOKED', 'EXPIRED')", name="ck_authority_event_status"),
    )
    op.create_index("ix_authority_profile_events_authority_profile_id", "authority_profile_events", ["authority_profile_id"])
    op.create_index("ix_authority_profile_events_effective_at", "authority_profile_events", ["effective_at"])
    op.execute("""
        CREATE FUNCTION reject_authority_event_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'authority lifecycle events are append-only'; END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER authority_event_immutable BEFORE UPDATE OR DELETE ON authority_profile_events FOR EACH ROW EXECUTE FUNCTION reject_authority_event_mutation()")


def downgrade():
    raise RuntimeError("Authority history is append-only; destructive downgrade forbidden")
