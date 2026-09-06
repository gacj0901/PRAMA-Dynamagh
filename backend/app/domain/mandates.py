from __future__ import annotations

import enum
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.persistence.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MandateStatus(str, enum.Enum):
    RECEIVED = "RECEIVED"
    PLANNED = "PLANNED"
    ACQUIRING = "ACQUIRING"
    EVALUATING = "EVALUATING"
    DECIDING = "DECIDING"
    DECIDED = "DECIDED"
    TICKETED = "TICKETED"
    FAILED = "FAILED"


class AcquisitionStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class AgentIdentityOrigin(str, enum.Enum):
    INTERNAL_AUTONOMY = "INTERNAL_AUTONOMY"
    EXTERNAL_API_AGENT = "EXTERNAL_API_AGENT"
    MCP_AGENT = "MCP_AGENT"
    LANGCHAIN_AGENT = "LANGCHAIN_AGENT"
    CREWAI_AGENT = "CREWAI_AGENT"
    OTHER = "OTHER"


class AgentIdentityStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class AgentIdentity(Base):
    """Persistent subject for autonomous attribution, not an authority grant."""

    __tablename__ = "agent_identities"
    __table_args__ = (UniqueConstraint("policy_id", name="uq_agent_identities_policy_id"),)

    agent_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentIdentityStatus.ACTIVE.value)
    policy_id: Mapped[str | None] = mapped_column(ForeignKey("autonomy_policies.policy_id"), nullable=True, index=True)
    trajectory_version: Mapped[str] = mapped_column(String(64), nullable=False, default="g13-agent-identity-v1")
    m2m_context_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)


class Mandate(Base):
    __tablename__ = "mandates"

    mandate_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    mandate_type: Mapped[str] = mapped_column(String(100), nullable=False, default="GENERAL")
    constraints: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    max_budget_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MandateStatus.RECEIVED.value)
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    agent_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    agent_identity_id: Mapped[str | None] = mapped_column(ForeignKey("agent_identities.agent_id"), nullable=True, index=True)
    m2m_context_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    client_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    autonomy_policy_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    autonomy_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class AcquisitionTask(Base):
    __tablename__ = "acquisition_tasks"

    acquisition_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.mandate_id", ondelete="CASCADE"), nullable=False, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    requested_intent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AcquisitionStatus.PENDING.value)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    telegraph_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    callback_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    onchain_output_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)


class MandateTransition(Base):
    __tablename__ = "mandate_transitions"

    transition_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.mandate_id", ondelete="CASCADE"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class TelegraphCall(Base):
    __tablename__ = "telegraph_calls"
    telegraph_call_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.mandate_id"), nullable=False, index=True)
    acquisition_id: Mapped[str] = mapped_column(ForeignKey("acquisition_tasks.acquisition_id"), nullable=False, unique=True, index=True)
    causal_request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    miner_id: Mapped[str | None] = mapped_column(String(255)); miner_name: Mapped[str | None] = mapped_column(String(255)); intent: Mapped[str | None] = mapped_column(String(255)); signal_hash: Mapped[str | None] = mapped_column(String(255))
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 6)); duration_ms: Mapped[int | None] = mapped_column(Integer); reasoning: Mapped[str | None] = mapped_column(Text); warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list); raw_response: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False); created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now); completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    __tablename__ = "usage_events"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[str | None] = mapped_column(ForeignKey("mandates.mandate_id"), nullable=True, index=True)
    acquisition_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class PublicManualSpendLedger(Base):
    """Durable daily public-spend total.  ``reserved + spent`` is the cap gate."""
    __tablename__ = "public_manual_spend_ledgers"

    spend_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reserved_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0.000000"))
    spent_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0.000000"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class PublicManualSpendReservation(Base):
    """One durable paid-workflow budget authorization, retained for audit.

    The table name is retained for G12 compatibility.  Reservations are now
    shared by MANUAL, M2M, and AUTONOMOUS paid workflows so the daily ledger is
    a single global cap rather than separate per-surface allowances.
    """
    __tablename__ = "public_manual_spend_reservations"

    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.mandate_id", ondelete="CASCADE"), primary_key=True)
    spend_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    reserved_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    actual_spend_usdc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="RESERVED")
    origin: Mapped[str] = mapped_column(String(32), nullable=False, default="MANUAL")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class M2MMandateRequest(Base):
    """Durable M2M idempotency record bound to one mandate and request hash."""

    __tablename__ = "m2m_mandate_requests"
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.mandate_id", ondelete="CASCADE"), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

class Evidence(Base):
    __tablename__="evidence"
    evidence_id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); mandate_id: Mapped[str]=mapped_column(String(36),index=True); acquisition_id: Mapped[str|None]=mapped_column(String(36), nullable=True); telegraph_call_id: Mapped[str|None]=mapped_column(String(36),unique=True, nullable=True); erc8183_job_id: Mapped[str|None]=mapped_column(ForeignKey("erc8183_jobs.erc8183_job_id"), nullable=True, index=True); evidence_type: Mapped[str]=mapped_column(String(64)); source_kind: Mapped[str]=mapped_column(String(32)); source_intent: Mapped[str|None]=mapped_column(String(255)); source_miner_id: Mapped[str|None]=mapped_column(String(255)); source_signal_hash: Mapped[str|None]=mapped_column(String(255)); normalized_payload: Mapped[dict]=mapped_column(JSONB); content_hash: Mapped[str]=mapped_column(String(66)); normalizer_version: Mapped[str]=mapped_column(String(64)); provenance_status: Mapped[str]=mapped_column(String(32)); admissibility: Mapped[str]=mapped_column(String(32)); limitation_codes: Mapped[list]=mapped_column(JSONB,default=list); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now)


class EpistemicTarget(Base):
    """Immutable target contract for the foundational O_EPISTEMIC layer."""

    __tablename__ = "epistemic_targets"

    target_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[str] = mapped_column(
        ForeignKey("mandates.mandate_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    temporal_scope: Mapped[dict] = mapped_column(JSONB, nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class EvidenceRequirement(Base):
    """Immutable, typed requirement contract for an EpistemicTarget."""

    __tablename__ = "evidence_requirements"
    __table_args__ = (
        UniqueConstraint(
            "target_id",
            "requirement_type",
            "contract_version",
            name="uq_evidence_requirements_target_type_version",
        ),
        CheckConstraint(
            "requirement_type IN ('asset_identity', 'quote_currency', 'price_value', 'temporal_applicability')",
            name="ck_evidence_requirements_crypto_price_v01_type",
        ),
    )

    requirement_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_id: Mapped[str] = mapped_column(
        ForeignKey("epistemic_targets.target_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class CryptoPriceEvidence(Base):
    """Typed CRYPTO_PRICE evidence extension; existing Evidence is untouched."""

    __tablename__ = "crypto_price_evidence"
    __table_args__ = (
        UniqueConstraint("evidence_id", name="uq_crypto_price_evidence_evidence_id"),
    )

    crypto_price_evidence_id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.evidence_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    asset: Mapped[str] = mapped_column(String(128), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(32), nullable=False)
    price_value: Mapped[Decimal] = mapped_column(Numeric(38, 18), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class EvidenceRelation(Base):
    """Immutable relation between one typed evidence artifact and requirement."""

    __tablename__ = "evidence_relations"
    __table_args__ = (
        UniqueConstraint(
            "target_id",
            "requirement_id",
            "evidence_id",
            "observer_version",
            "contract_version",
            name="uq_evidence_relations_lineage_version",
        ),
        CheckConstraint(
            "relation_state IN ('SATISFIES', 'CONTRADICTS', 'UNRESOLVED', 'NOT_APPLICABLE')",
            name="ck_evidence_relations_state",
        ),
    )

    relation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    target_id: Mapped[str] = mapped_column(
        ForeignKey("epistemic_targets.target_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requirement_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_requirements.requirement_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        ForeignKey("evidence.evidence_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    relation_basis: Mapped[dict] = mapped_column(JSONB, nullable=False)
    observer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class EpistemicEvaluation(Base):
    """Immutable deterministic E1 relational snapshot; it has no decision authority."""

    __tablename__ = "epistemic_evaluations"
    __table_args__ = (
        CheckConstraint(
            "structural_state IN ('COMPLETE', 'INCOMPLETE', 'CONTRADICTED')",
            name="ck_epistemic_evaluations_structural_state",
        ),
    )

    evaluation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[str] = mapped_column(
        ForeignKey("mandates.mandate_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_id: Mapped[str] = mapped_column(
        ForeignKey("epistemic_targets.target_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_set_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    requirement_states: Mapped[list] = mapped_column(JSONB, nullable=False)
    relations: Mapped[list] = mapped_column(JSONB, nullable=False)
    contradictions: Mapped[list] = mapped_column(JSONB, nullable=False)
    limitations: Mapped[list] = mapped_column(JSONB, nullable=False)
    structural_state: Mapped[str] = mapped_column(String(32), nullable=False)
    observer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_version: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False)
    source_evidence_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    canonical_hash: Mapped[str] = mapped_column(String(66), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class StructuralEvaluation(Base):
    __tablename__="structural_evaluations"
    evaluation_id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); mandate_id: Mapped[str]=mapped_column(String(36)); evaluator: Mapped[str]=mapped_column(String(64)); evaluator_version: Mapped[str]=mapped_column(String(64)); evidence_set_hash: Mapped[str]=mapped_column(String(66)); admitted_evidence_ids: Mapped[list]=mapped_column(JSONB); limited_evidence_ids: Mapped[list]=mapped_column(JSONB); rejected_evidence_ids: Mapped[list]=mapped_column(JSONB); limitation_codes: Mapped[list]=mapped_column(JSONB); contradiction_codes: Mapped[list]=mapped_column(JSONB); structural_state: Mapped[str]=mapped_column(String(64)); evaluation_payload: Mapped[dict]=mapped_column(JSONB); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); completed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now)
class Decision(Base):
    __tablename__="decisions"
    decision_id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); mandate_id: Mapped[str]=mapped_column(String(36)); evaluation_id: Mapped[str]=mapped_column(String(36),unique=True); state: Mapped[str]=mapped_column(String(16)); policy_version: Mapped[str]=mapped_column(String(64)); evidence_set_hash: Mapped[str]=mapped_column(String(66)); reason_codes: Mapped[list]=mapped_column(JSONB); decision_payload: Mapped[dict]=mapped_column(JSONB); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); completed_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now)
class Ticket(Base):
    __tablename__="tickets"
    ticket_id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); mandate_id: Mapped[str]=mapped_column(String(36)); decision_id: Mapped[str]=mapped_column(String(36)); schema_version: Mapped[str]=mapped_column(String(64)); canonical_payload: Mapped[dict]=mapped_column(JSONB); ticket_hash: Mapped[str]=mapped_column(String(66),unique=True); hash_algorithm: Mapped[str]=mapped_column(String(32)); anchor_status: Mapped[str]=mapped_column(String(32)); chain_id: Mapped[int|None]=mapped_column(Integer); contract_address: Mapped[str|None]=mapped_column(String(255)); tx_hash: Mapped[str|None]=mapped_column(String(255)); block_number: Mapped[int|None]=mapped_column(Integer); block_hash: Mapped[str|None]=mapped_column(String(66)); onchain_output_hash: Mapped[str|None]=mapped_column(String(255)); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now)


class AnchorAttempt(Base):
    __tablename__ = "anchor_attempts"
    __table_args__ = (UniqueConstraint("ticket_id", name="uq_anchor_attempt_ticket"),)

    anchor_attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    ticket_id: Mapped[str] = mapped_column(ForeignKey("tickets.ticket_id", ondelete="CASCADE"), nullable=False)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_address: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    tx_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    block_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ERC8183Job(Base):
    __tablename__ = "erc8183_jobs"
    __table_args__ = (UniqueConstraint("chain_id", "diamond_address", "telegraph_job_id", name="uq_erc8183_chain_diamond_job"),)

    erc8183_job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    mandate_id: Mapped[str | None] = mapped_column(ForeignKey("mandates.mandate_id"), nullable=True, index=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.ticket_id"), nullable=True, index=True)
    chain_id: Mapped[int] = mapped_column(Integer, nullable=False)
    diamond_address: Mapped[str] = mapped_column(String(42), nullable=False)
    telegraph_job_id: Mapped[str | None] = mapped_column(String(78), nullable=True)
    intent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_id: Mapped[str] = mapped_column(String(66), nullable=False)
    callback_address: Mapped[str] = mapped_column(String(42), nullable=False)
    callback_response_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    callback_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    callback_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    params_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    chain_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    budget_usdc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    miner_payment_usdc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    protocol_fee_usdc: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    approval_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    approval_block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deposit_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    deposit_block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    create_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    create_block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terminal_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    terminal_block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_tx_hash: Mapped[str | None] = mapped_column(String(66), nullable=True)
    cancel_block_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    terminal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutonomyPolicy(Base):
    __tablename__ = "autonomy_policies"
    policy_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="autonomy-policy-v0")
    mandate_template: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    acquisition_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    allow_telegraph_http: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_erc8183: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_anchor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    strict_verification: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    read_only_replay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cadence_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    dedupe_window_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    max_usdc_per_run: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0.050000"))
    max_usdc_per_day: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0.200000"))
    max_runs_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    max_concurrent_runs: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AutonomyRun(Base):
    __tablename__ = "autonomy_runs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_autonomy_run_idempotency"),)
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    policy_id: Mapped[str] = mapped_column(ForeignKey("autonomy_policies.policy_id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="SCHEDULED")
    agent_identity_id: Mapped[str | None] = mapped_column(ForeignKey("agent_identities.agent_id"), nullable=True, index=True)
    mandate_id: Mapped[str | None] = mapped_column(ForeignKey("mandates.mandate_id"), nullable=True, index=True)
    erc8183_job_id: Mapped[str | None] = mapped_column(ForeignKey("erc8183_jobs.erc8183_job_id"), nullable=True, index=True)
    ticket_id: Mapped[str | None] = mapped_column(ForeignKey("tickets.ticket_id"), nullable=True, index=True)
    planned_cost_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0.000000"))
    actual_cost_usdc: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False, default=Decimal("0.000000"))
    skip_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class OEvidenceProvenanceContract(Base):
    __tablename__ = "o_evidence_provenance_contracts"
    observer_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    observer_version: Mapped[str] = mapped_column(String(32), nullable=False)
    boundary: Mapped[list] = mapped_column(JSONB, nullable=False)
    required_invariants: Mapped[list] = mapped_column(JSONB, nullable=False)
    normalization: Mapped[str] = mapped_column(String(32), nullable=False)
    context_fields: Mapped[list] = mapped_column(JSONB, nullable=False)
    min_context_count: Mapped[int] = mapped_column(Integer, nullable=False)
    min_global_count: Mapped[int] = mapped_column(Integer, nullable=False)
    kernel_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sigma_op_status: Mapped[str] = mapped_column(String(32), nullable=False)
    u_lambda_status: Mapped[str] = mapped_column(String(32), nullable=False)
    capability: Mapped[str] = mapped_column(String(255), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class OEvidenceProvenanceGlobalState(Base):
    __tablename__ = "o_evidence_provenance_global_states"
    observer_id: Mapped[str] = mapped_column(
        ForeignKey("o_evidence_provenance_contracts.observer_id", ondelete="CASCADE"),
        primary_key=True,
    )
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    omega_sum: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False, default=Decimal("0"))
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class OEvidenceProvenanceContextState(Base):
    __tablename__ = "o_evidence_provenance_context_states"
    __table_args__ = (UniqueConstraint("observer_id", "miner_id", "intent", name="uq_o_evidence_provenance_context"),)
    observer_id: Mapped[str] = mapped_column(
        ForeignKey("o_evidence_provenance_contracts.observer_id", ondelete="CASCADE"),
        primary_key=True,
    )
    miner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    intent: Mapped[str] = mapped_column(String(128), primary_key=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    omega_sum: Mapped[Decimal] = mapped_column(Numeric(18, 12), nullable=False, default=Decimal("0"))
    kernel_state: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    last_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class OEvidenceProvenanceObservation(Base):
    __tablename__ = "o_evidence_provenance_observations"
    observation_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    observer_id: Mapped[str] = mapped_column(
        ForeignKey("o_evidence_provenance_contracts.observer_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mandate_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    acquisition_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    telegraph_call_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True, index=True)
    evidence_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    miner_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    intent: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    omega: Mapped[int] = mapped_column(Integer, nullable=False)
    expected: Mapped[Decimal | None] = mapped_column(Numeric(18, 15), nullable=True)
    support_status: Mapped[str] = mapped_column(String(32), nullable=False)
    context_count_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    global_count_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_artifact_ids: Mapped[dict] = mapped_column(JSONB, nullable=False)
    kernel_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    observation_hash: Mapped[str] = mapped_column(String(66), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
