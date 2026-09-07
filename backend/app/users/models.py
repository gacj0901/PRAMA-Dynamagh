import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.persistence.database import Base
from app.domain.mandates import utc_now


class UserIdentity(Base):
    __tablename__ = 'user_identities'
    user_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default='ACTIVE', nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserSession(Base):
    __tablename__ = 'user_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('user_identities.user_id'), index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserCreditAccount(Base):
    __tablename__ = 'user_credit_accounts'
    user_id: Mapped[str] = mapped_column(ForeignKey('user_identities.user_id'), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserMandate(Base):
    __tablename__ = 'user_mandates'
    __table_args__ = (UniqueConstraint('user_id', 'request_key', name='uq_user_mandate_request'),)
    mandate_id: Mapped[str] = mapped_column(ForeignKey('mandates.mandate_id'), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('user_credit_accounts.user_id'), index=True, nullable=False)
    request_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class UserCreditLedger(Base):
    __tablename__ = 'user_credit_ledger'
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey('user_credit_accounts.user_id'), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    mandate_id: Mapped[str | None] = mapped_column(ForeignKey('user_mandates.mandate_id'), index=True)
    acquisition_id: Mapped[str | None] = mapped_column(ForeignKey('acquisition_tasks.acquisition_id'))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
