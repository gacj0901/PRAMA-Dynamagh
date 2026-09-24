"""Widen inbound x402 assets and persist scoped result capability digests.

Revision ID: 0032_inbound_x402_result_capability
Revises: 0031_inbound_x402_payments
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_inbound_x402_result_capability"
down_revision = "0031_inbound_x402_payments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "inbound_x402_payments",
        "asset",
        existing_type=sa.String(length=32),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
    op.add_column(
        "inbound_x402_payments",
        sa.Column("result_capability_hash", sa.String(length=64), nullable=True),
    )
    # Alembic's default version table uses VARCHAR(32), but this revision ID
    # is 36 characters. Widen it before Alembic records this revision.
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Keep alembic_version.version_num at 64: the current revision ID is still
    # stored there until Alembic records the downgrade target after this runs.
    op.drop_column("inbound_x402_payments", "result_capability_hash")
    op.alter_column(
        "inbound_x402_payments",
        "asset",
        existing_type=sa.String(length=255),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
