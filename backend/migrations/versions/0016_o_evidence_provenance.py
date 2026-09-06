"""Freeze O_EVIDENCE_PROVENANCE v0.1 contract and state."""

from datetime import datetime, timezone
from decimal import Decimal

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0016_o_evidence_provenance"
down_revision = "0015_g13_agent_identity"
branch_labels = None
depends_on = None


OBSERVER_ID = "o-evidence-provenance-v0.1"
FROZEN_AT = datetime(2026, 9, 6, 9, 1, 2, 321073, tzinfo=timezone.utc)
KERNEL_CONFIG = {
    "h": 1.0,
    "tau": 336.0,
    "theta_scale": 2.0,
    "lambda_0": 1.0,
    "lambda_min": 0.1,
    "lambda_max": 1.0,
    "kappa_v3": 9.957514604354753e-7,
    "g_smooth": 24,
    "delta_ref": 1.0,
}
INVARIANTS = [
    "AcquisitionTask.mandate_id == Mandate.mandate_id",
    "TelegraphCall.mandate_id == Mandate.mandate_id",
    "TelegraphCall.acquisition_id == AcquisitionTask.acquisition_id",
    "Evidence.mandate_id == Mandate.mandate_id",
    "Evidence.acquisition_id == TelegraphCall.acquisition_id",
    "Evidence.telegraph_call_id == TelegraphCall.telegraph_call_id",
    "Evidence.source_intent == TelegraphCall.intent",
    "Evidence.source_miner_id == TelegraphCall.miner_id",
    "Evidence.source_signal_hash == TelegraphCall.signal_hash",
    "completed rows require successful acquisition/call and required source fields",
]


def upgrade() -> None:
    json_type = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "o_evidence_provenance_contracts",
        sa.Column("observer_id", sa.String(length=64), primary_key=True),
        sa.Column("observer_version", sa.String(length=32), nullable=False),
        sa.Column("boundary", json_type, nullable=False),
        sa.Column("required_invariants", json_type, nullable=False),
        sa.Column("normalization", sa.String(length=32), nullable=False),
        sa.Column("context_fields", json_type, nullable=False),
        sa.Column("min_context_count", sa.Integer(), nullable=False),
        sa.Column("min_global_count", sa.Integer(), nullable=False),
        sa.Column("kernel_config", json_type, nullable=False),
        sa.Column("sigma_op_status", sa.String(length=32), nullable=False),
        sa.Column("u_lambda_status", sa.String(length=32), nullable=False),
        sa.Column("capability", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "o_evidence_provenance_global_states",
        sa.Column("observer_id", sa.String(length=64), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("omega_sum", sa.Numeric(18, 12), nullable=False, server_default="0"),
        sa.Column("next_sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["observer_id"], ["o_evidence_provenance_contracts.observer_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("observer_id"),
    )
    op.create_table(
        "o_evidence_provenance_context_states",
        sa.Column("observer_id", sa.String(length=64), nullable=False),
        sa.Column("miner_id", sa.String(length=128), nullable=False),
        sa.Column("intent", sa.String(length=128), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("omega_sum", sa.Numeric(18, 12), nullable=False, server_default="0"),
        sa.Column("kernel_state", json_type, nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["observer_id"], ["o_evidence_provenance_contracts.observer_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("observer_id", "miner_id", "intent"),
        sa.UniqueConstraint("observer_id", "miner_id", "intent", name="uq_o_evidence_provenance_context"),
    )
    op.create_table(
        "o_evidence_provenance_observations",
        sa.Column("observation_id", sa.String(length=36), primary_key=True),
        sa.Column("observer_id", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mandate_id", sa.String(length=36), nullable=True),
        sa.Column("acquisition_id", sa.String(length=36), nullable=True),
        sa.Column("telegraph_call_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_id", sa.String(length=36), nullable=True),
        sa.Column("miner_id", sa.String(length=128), nullable=True),
        sa.Column("intent", sa.String(length=128), nullable=True),
        sa.Column("omega", sa.Integer(), nullable=False),
        sa.Column("expected", sa.Numeric(18, 15), nullable=True),
        sa.Column("support_status", sa.String(length=32), nullable=False),
        sa.Column("context_count_before", sa.Integer(), nullable=True),
        sa.Column("global_count_before", sa.Integer(), nullable=True),
        sa.Column("source_artifact_ids", json_type, nullable=False),
        sa.Column("kernel_output", json_type, nullable=True),
        sa.Column("observation_hash", sa.String(length=66), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["observer_id"], ["o_evidence_provenance_contracts.observer_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("telegraph_call_id", name="uq_o_evidence_provenance_call"),
        sa.UniqueConstraint("observation_hash", name="uq_o_evidence_provenance_hash"),
    )
    for table, column in (
        ("o_evidence_provenance_global_states", "observer_id"),
        ("o_evidence_provenance_context_states", "observer_id"),
        ("o_evidence_provenance_observations", "observer_id"),
        ("o_evidence_provenance_observations", "mandate_id"),
        ("o_evidence_provenance_observations", "acquisition_id"),
        ("o_evidence_provenance_observations", "telegraph_call_id"),
        ("o_evidence_provenance_observations", "evidence_id"),
        ("o_evidence_provenance_observations", "miner_id"),
        ("o_evidence_provenance_observations", "intent"),
    ):
        op.create_index(f"ix_{table}_{column}", table, [column])

    contracts = sa.table(
        "o_evidence_provenance_contracts",
        sa.column("observer_id", sa.String),
        sa.column("observer_version", sa.String),
        sa.column("boundary", json_type),
        sa.column("required_invariants", json_type),
        sa.column("normalization", sa.String),
        sa.column("context_fields", json_type),
        sa.column("min_context_count", sa.Integer),
        sa.column("min_global_count", sa.Integer),
        sa.column("kernel_config", json_type),
        sa.column("sigma_op_status", sa.String),
        sa.column("u_lambda_status", sa.String),
        sa.column("capability", sa.String),
        sa.column("mode", sa.String),
        sa.column("frozen_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        contracts,
        [{
            "observer_id": OBSERVER_ID,
            "observer_version": "0.1",
            "boundary": ["Mandate", "AcquisitionTask", "TelegraphCall", "Evidence"],
            "required_invariants": INVARIANTS,
            "normalization": "identity",
            "context_fields": ["miner_id", "intent"],
            "min_context_count": 2,
            "min_global_count": 2,
            "kernel_config": KERNEL_CONFIG,
            "sigma_op_status": "NOT_APPLICABLE",
            "u_lambda_status": "NOT_APPLICABLE",
            "capability": "K1 memory-only structural trajectory observation of persisted provenance discontinuity",
            "mode": "SHADOW",
            "frozen_at": FROZEN_AT,
            "created_at": FROZEN_AT,
        }],
    )
    states = sa.table(
        "o_evidence_provenance_global_states",
        sa.column("observer_id", sa.String),
        sa.column("observation_count", sa.Integer),
        sa.column("omega_sum", sa.Numeric),
        sa.column("next_sequence", sa.Integer),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(states, [{
        "observer_id": OBSERVER_ID,
        "observation_count": 0,
        "omega_sum": Decimal("0"),
        "next_sequence": 1,
        "updated_at": FROZEN_AT,
    }])


def downgrade() -> None:
    op.drop_table("o_evidence_provenance_observations")
    op.drop_table("o_evidence_provenance_context_states")
    op.drop_table("o_evidence_provenance_global_states")
    op.drop_table("o_evidence_provenance_contracts")
