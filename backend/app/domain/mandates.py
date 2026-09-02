from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
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

class Evidence(Base):
    __tablename__="evidence"
    evidence_id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4())); mandate_id: Mapped[str]=mapped_column(String(36),index=True); acquisition_id: Mapped[str|None]=mapped_column(String(36), nullable=True); telegraph_call_id: Mapped[str|None]=mapped_column(String(36),unique=True, nullable=True); erc8183_job_id: Mapped[str|None]=mapped_column(ForeignKey("erc8183_jobs.erc8183_job_id"), nullable=True, index=True); evidence_type: Mapped[str]=mapped_column(String(64)); source_kind: Mapped[str]=mapped_column(String(32)); source_intent: Mapped[str|None]=mapped_column(String(255)); source_miner_id: Mapped[str|None]=mapped_column(String(255)); source_signal_hash: Mapped[str|None]=mapped_column(String(255)); normalized_payload: Mapped[dict]=mapped_column(JSONB); content_hash: Mapped[str]=mapped_column(String(66)); normalizer_version: Mapped[str]=mapped_column(String(64)); provenance_status: Mapped[str]=mapped_column(String(32)); admissibility: Mapped[str]=mapped_column(String(32)); limitation_codes: Mapped[list]=mapped_column(JSONB,default=list); created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now); updated_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=utc_now)
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
