"""Persist generic internal-only campaign classification on mandates."""

from alembic import op
import sqlalchemy as sa


revision = "0033_internal_mandate_visibility"
down_revision = "0032_inbound_x402_result_capability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mandates",
        sa.Column("visibility", sa.String(length=32), server_default="PUBLIC", nullable=False),
    )
    op.add_column("mandates", sa.Column("campaign_id", sa.String(length=128), nullable=True))
    op.add_column("mandates", sa.Column("case_id", sa.String(length=128), nullable=True))
    op.add_column("mandates", sa.Column("purpose", sa.String(length=128), nullable=True))
    op.create_index("ix_mandates_campaign_id", "mandates", ["campaign_id"])
    op.create_index("ix_mandates_case_id", "mandates", ["case_id"])


def downgrade() -> None:
    op.drop_index("ix_mandates_case_id", table_name="mandates")
    op.drop_index("ix_mandates_campaign_id", table_name="mandates")
    op.drop_column("mandates", "purpose")
    op.drop_column("mandates", "case_id")
    op.drop_column("mandates", "campaign_id")
    op.drop_column("mandates", "visibility")
