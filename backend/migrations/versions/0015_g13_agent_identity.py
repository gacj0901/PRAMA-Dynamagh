"""persist G13-A agent identities and G13-B lineage references"""

from alembic import op
import sqlalchemy as sa


revision = "0015_g13_agent_identity"
down_revision = "0014_m2m_rail"
branch_labels = None
depends_on = None


BOUNDED_POLICY_NAME = "prama-bounded-telegraph-http-v1"
INTERNAL_AGENT_ID = "autonomy-controller"
TRAJECTORY_VERSION = "g13-agent-identity-v1"


def upgrade() -> None:
    op.create_table(
        "agent_identities",
        sa.Column("agent_id", sa.String(255), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="ACTIVE"),
        sa.Column("policy_id", sa.String(36), sa.ForeignKey("autonomy_policies.policy_id"), nullable=True),
        sa.Column("trajectory_version", sa.String(64), nullable=False, server_default=TRAJECTORY_VERSION),
        sa.Column("m2m_context_id", sa.String(128), nullable=True),
        sa.UniqueConstraint("policy_id", name="uq_agent_identities_policy_id"),
    )
    op.create_index("ix_agent_identities_policy_id", "agent_identities", ["policy_id"])
    op.create_index("ix_agent_identities_m2m_context_id", "agent_identities", ["m2m_context_id"])
    op.add_column(
        "mandates",
        sa.Column("agent_identity_id", sa.String(255), sa.ForeignKey("agent_identities.agent_id"), nullable=True),
    )
    op.create_index("ix_mandates_agent_identity_id", "mandates", ["agent_identity_id"])
    op.add_column("mandates", sa.Column("m2m_context_id", sa.String(128), nullable=True))
    op.create_index("ix_mandates_m2m_context_id", "mandates", ["m2m_context_id"])
    op.add_column(
        "autonomy_runs",
        sa.Column("agent_identity_id", sa.String(255), sa.ForeignKey("agent_identities.agent_id"), nullable=True),
    )
    op.create_index("ix_autonomy_runs_agent_identity_id", "autonomy_runs", ["agent_identity_id"])

    # Bind the explicitly seeded bounded policy to one durable internal subject.
    # If a deployment does not have that policy row, no identity is fabricated;
    # the paid scheduler will fail closed until an operator repairs the binding.
    op.execute(
        sa.text(
            """
            INSERT INTO agent_identities
                (agent_id, name, origin, created_at, status, policy_id, trajectory_version)
            SELECT :agent_id, :agent_id, 'INTERNAL_AUTONOMY', NOW(), 'ACTIVE', policy_id, :trajectory_version
            FROM autonomy_policies
            WHERE name = :policy_name
            ON CONFLICT (agent_id) DO UPDATE
              SET policy_id = EXCLUDED.policy_id
            WHERE agent_identities.origin = 'INTERNAL_AUTONOMY'
            """
        ).bindparams(
            agent_id=INTERNAL_AGENT_ID,
            policy_name=BOUNDED_POLICY_NAME,
            trajectory_version=TRAJECTORY_VERSION,
        )
    )

    # These links use already persisted, explicit attribution only.  No identity
    # is inferred for manual rows or historical rows without an agent_id.
    op.execute(
        sa.text(
            """
            INSERT INTO agent_identities
                (agent_id, name, origin, created_at, status, policy_id, trajectory_version)
            SELECT m.agent_id, m.agent_id, 'EXTERNAL_API_AGENT', MIN(m.created_at), 'ACTIVE', NULL, :trajectory_version
            FROM mandates m
            WHERE m.origin = 'M2M' AND m.agent_id IS NOT NULL
            GROUP BY m.agent_id
            ON CONFLICT (agent_id) DO NOTHING
            """
        ).bindparams(trajectory_version=TRAJECTORY_VERSION)
    )
    op.execute(
        sa.text(
            """
            UPDATE mandates m
            SET agent_identity_id = i.agent_id
            FROM agent_identities i
            WHERE m.agent_identity_id IS NULL
              AND m.agent_id = i.agent_id
              AND (
                    (m.origin = 'M2M' AND i.origin = 'EXTERNAL_API_AGENT')
                 OR (m.origin = 'AUTONOMOUS' AND i.origin = 'INTERNAL_AUTONOMY')
              )
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE autonomy_runs r
            SET agent_identity_id = m.agent_identity_id
            FROM mandates m
            WHERE r.agent_identity_id IS NULL
              AND r.mandate_id = m.mandate_id
              AND m.agent_identity_id IS NOT NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_index("ix_autonomy_runs_agent_identity_id", table_name="autonomy_runs")
    op.drop_column("autonomy_runs", "agent_identity_id")
    op.drop_index("ix_mandates_agent_identity_id", table_name="mandates")
    op.drop_index("ix_mandates_m2m_context_id", table_name="mandates")
    op.drop_column("mandates", "m2m_context_id")
    op.drop_column("mandates", "agent_identity_id")
    op.drop_index("ix_agent_identities_m2m_context_id", table_name="agent_identities")
    op.drop_index("ix_agent_identities_policy_id", table_name="agent_identities")
    op.drop_table("agent_identities")
