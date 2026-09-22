"""Persist the effective G13 policy version per agent."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from app.authority.binding import binding_hash, binding_id, canonical_binding_material


revision = "0029_g13_policy_binding"
down_revision = "0028_acquisition_access_plane"
branch_labels = None
depends_on = None


def upgrade():
    for name, type_ in (
        ("effective_policy_version", sa.String(64)),
        ("policy_binding_id", sa.String(36)),
        ("policy_binding_hash", sa.String(66)),
        ("source_transition_id", sa.String(255)),
        ("recovery_event_id", sa.String(36)),
    ):
        op.add_column("policy_evaluations", sa.Column(name, type_, nullable=True))
    op.create_table(
        "g13_policy_bindings",
        sa.Column("binding_id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(255), sa.ForeignKey("agent_identities.agent_id"), nullable=False),
        sa.Column("effective_policy_version", sa.String(64), nullable=False),
        sa.Column("previous_policy_version", sa.String(64), nullable=True),
        sa.Column("source_transition_type", sa.String(64), nullable=False),
        sa.Column("source_transition_id", sa.String(255), nullable=False),
        sa.Column("recovery_event_id", sa.String(36), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("canonical_hash", sa.String(66), nullable=False),
        sa.UniqueConstraint("agent_id", name="uq_g13_policy_binding_agent"),
    )
    op.create_index("ix_g13_policy_bindings_agent_id", "g13_policy_bindings", ["agent_id"])
    op.create_index("ix_g13_policy_bindings_recovery_event_id", "g13_policy_bindings", ["recovery_event_id"])

    # Explicit backfill for the production autonomy-controller transition.
    # Empty/test databases remain fail-closed until an explicit transition is
    # recorded; no v0.2 default is inserted here.
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            """
            SELECT event_id, created_at, metadata
            FROM usage_events
            WHERE event_id = :event_id
              AND event_type = 'G13_RECOVERY_EVENT'
            """
        ),
        {"event_id": "58b29161-925f-513d-80be-1bbc9fa91b7d"},
    ).mappings().first()
    if row is not None:
        metadata = dict(row["metadata"] or {})
        agent_id = str(metadata["agent_identity_id"])
        effective = str(metadata["policy_version"])
        previous = str(metadata["previous_policy_version"])
        activated_at = row["created_at"]
        material = canonical_binding_material(
            agent_id=agent_id,
            effective_policy_version=effective,
            previous_policy_version=previous,
            source_transition_type="G13_RECOVERY_EVENT",
            source_transition_id=str(row["event_id"]),
            recovery_event_id=str(row["event_id"]),
            activated_at=activated_at,
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO g13_policy_bindings
                (binding_id, agent_id, effective_policy_version,
                 previous_policy_version, source_transition_type,
                 source_transition_id, recovery_event_id, activated_at,
                 canonical_hash)
                VALUES (:binding_id, :agent_id, :effective_policy_version,
                        :previous_policy_version, :source_transition_type,
                        :source_transition_id, :recovery_event_id,
                        :activated_at, :canonical_hash)
                ON CONFLICT (agent_id) DO NOTHING
                """
            ),
            {
                "binding_id": binding_id(material),
                "agent_id": agent_id,
                "effective_policy_version": effective,
                "previous_policy_version": previous,
                "source_transition_type": "G13_RECOVERY_EVENT",
                "source_transition_id": str(row["event_id"]),
                "recovery_event_id": str(row["event_id"]),
                "activated_at": activated_at,
                "canonical_hash": binding_hash(material),
            },
        )


def downgrade():
    raise RuntimeError("G13 policy binding history is append-only; destructive downgrade forbidden")
