"""authenticated M2M rail and bounded autonomous demo policy"""

from alembic import op
import sqlalchemy as sa


revision = "0014_m2m_rail"
down_revision = "0013_public_execution_safety"
branch_labels = None
depends_on = None


BOUNDED_POLICY_ID = "d4b4e4c8-5d42-4a4e-8d1b-6e04a3d4c2a1"
BOUNDED_POLICY_NAME = "prama-bounded-telegraph-http-v1"


def upgrade() -> None:
    op.add_column("mandates", sa.Column("agent_id", sa.String(255), nullable=True))
    op.add_column("mandates", sa.Column("client_id", sa.String(255), nullable=True))
    op.create_index("ix_mandates_agent_id", "mandates", ["agent_id"])
    op.create_index("ix_mandates_client_id", "mandates", ["client_id"])
    op.add_column(
        "public_manual_spend_reservations",
        sa.Column("origin", sa.String(32), nullable=False, server_default="MANUAL"),
    )
    op.create_table(
        "m2m_mandate_requests",
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("agent_id", sa.String(255), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("mandate_id", sa.String(36), sa.ForeignKey("mandates.mandate_id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_m2m_mandate_requests_mandate_id", "m2m_mandate_requests", ["mandate_id"])

    # Seed one executable policy as disabled/DRAFT.  It remains inert until
    # the operator has separately validated the M2M rail and enables it.
    op.execute(
        sa.text(
            """
            INSERT INTO autonomy_policies
              (policy_id, name, enabled, version, mandate_template,
               acquisition_mode, allow_telegraph_http, allow_erc8183,
               allow_anchor, strict_verification, read_only_replay,
               cadence_seconds, dedupe_window_seconds, max_usdc_per_run,
               max_usdc_per_day, max_runs_per_day, max_concurrent_runs,
               state, created_at, updated_at)
            VALUES
              (:policy_id, :name, false, 'autonomy-policy-v0',
               CAST(:mandate_template AS jsonb), 'TELEGRAPH_HTTP', true, false,
               false, true, false, 900, 900, 0.010000, 0.030000, 3, 1,
               'DRAFT', NOW(), NOW())
            ON CONFLICT (name) DO NOTHING
            """
        ).bindparams(
            policy_id=BOUNDED_POLICY_ID,
            name=BOUNDED_POLICY_NAME,
            mandate_template='{"title":"PRAMA bounded autonomous observation","instruction":"What is the current price of Bitcoin in USD?"}',
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM autonomy_policies WHERE policy_id = :policy_id").bindparams(policy_id=BOUNDED_POLICY_ID))
    op.drop_index("ix_m2m_mandate_requests_mandate_id", table_name="m2m_mandate_requests")
    op.drop_table("m2m_mandate_requests")
    op.drop_column("public_manual_spend_reservations", "origin")
    op.drop_index("ix_mandates_client_id", table_name="mandates")
    op.drop_index("ix_mandates_agent_id", table_name="mandates")
    op.drop_column("mandates", "client_id")
    op.drop_column("mandates", "agent_id")
