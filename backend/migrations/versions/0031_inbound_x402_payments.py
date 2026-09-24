"""Inbound x402 payment rail — separate Leg 1 persistence.

Introduces `inbound_x402_payments`, the durable record for the economic fact
"external agent paid PRAMA-Dynamagh" (Leg 1).  This is intentionally separate
from:

  * the `Mandate` row (identity + authority) — linked via `mandate_id` only
    after verify+settle is confirmed;
  * the outbound payment leg PRAMA -> Telegraph (Leg 2), which is recorded by
    the existing Gateway x402 store and is *never* reused for Leg 1.

The wallet address is the economic principal, not the agent identity.  An
optional `external_agent_id` (declared via X-Agent-Id) lives on the Mandate,
not here, so we never fabricate identity from a wallet.
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_inbound_x402_payments"
down_revision = "0030_eval_binding_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inbound_x402_payments",
        sa.Column("payment_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        # Nullable until the Mandate is created post-settle.  FK keeps lineage
        # without fabricating one before the payment is real.
        sa.Column(
            "mandate_id",
            sa.String(36),
            sa.ForeignKey("mandates.mandate_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("payer_wallet_address", sa.String(64), nullable=False),
        sa.Column("recipient_wallet_address", sa.String(64), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("amount_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("facilitator", sa.String(128), nullable=False),
        # PRESENTED -> VERIFIED -> SETTLED ; FAILED_* terminal
        sa.Column("payment_status", sa.String(32), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=True),
        sa.Column("settlement_reference", sa.String(255), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        # Idempotency: keyed on the caller-supplied Idempotency-Key when
        # present, else on hash(payer_wallet || request payload digest).
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "payment_status IN ('PRESENTED','VERIFIED','SETTLED','FAILED_VERIFY','FAILED_SETTLE','REFUNDED')",
            name="ck_inbound_x402_status",
        ),
    )
    op.create_index(
        "ix_inbound_x402_payer_wallet", "inbound_x402_payments", ["payer_wallet_address"]
    )
    op.create_index(
        "ix_inbound_x402_request_id", "inbound_x402_payments", ["request_id"]
    )
    op.create_index(
        "ix_inbound_x402_mandate_id", "inbound_x402_payments", ["mandate_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_inbound_x402_mandate_id", table_name="inbound_x402_payments")
    op.drop_index("ix_inbound_x402_request_id", table_name="inbound_x402_payments")
    op.drop_index("ix_inbound_x402_payer_wallet", table_name="inbound_x402_payments")
    op.drop_table("inbound_x402_payments")
