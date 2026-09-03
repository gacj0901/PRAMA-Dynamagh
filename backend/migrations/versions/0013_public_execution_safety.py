"""durable public manual spend authorization"""

from alembic import op
import sqlalchemy as sa


revision = "0013_public_execution_safety"
down_revision = "0012_autonomy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "public_manual_spend_ledgers",
        sa.Column("spend_date", sa.Date(), primary_key=True),
        sa.Column("reserved_usdc", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("spent_usdc", sa.Numeric(18, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "public_manual_spend_reservations",
        sa.Column("mandate_id", sa.String(36), sa.ForeignKey("mandates.mandate_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("spend_date", sa.Date(), nullable=False),
        sa.Column("reserved_usdc", sa.Numeric(18, 6), nullable=False),
        sa.Column("actual_spend_usdc", sa.Numeric(18, 6), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_public_manual_spend_reservations_spend_date", "public_manual_spend_reservations", ["spend_date"])
    # Preserve the cap semantics from the moment the migration lands: previous
    # successful manual calls count as completed spend, never as a reservation.
    op.execute(
        """
        INSERT INTO public_manual_spend_ledgers
            (spend_date, reserved_usdc, spent_usdc, created_at, updated_at)
        SELECT (COALESCE(tc.completed_at, tc.created_at) AT TIME ZONE 'UTC')::date,
               0, COALESCE(SUM(tc.cost_usd), 0), NOW(), NOW()
        FROM telegraph_calls tc
        JOIN mandates m ON m.mandate_id = tc.mandate_id
        WHERE m.origin = 'MANUAL' AND tc.status = 'SUCCEEDED'
        GROUP BY (COALESCE(tc.completed_at, tc.created_at) AT TIME ZONE 'UTC')::date
        ON CONFLICT (spend_date) DO UPDATE
        SET spent_usdc = public_manual_spend_ledgers.spent_usdc + EXCLUDED.spent_usdc,
            updated_at = NOW()
        """
    )


def downgrade() -> None:
    op.drop_index("ix_public_manual_spend_reservations_spend_date", table_name="public_manual_spend_reservations")
    op.drop_table("public_manual_spend_reservations")
    op.drop_table("public_manual_spend_ledgers")
