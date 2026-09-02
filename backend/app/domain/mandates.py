from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
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
    mandate_id: Mapped[str] = mapped_column(ForeignKey("mandates.mandate_id"), nullable=False, index=True)
    acquisition_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
