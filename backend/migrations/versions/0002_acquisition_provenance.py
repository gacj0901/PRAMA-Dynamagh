"""add acquisition provenance

Revision ID: 0002_acquisition_provenance
Revises: 0001_mandate_state
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
revision="0002_acquisition_provenance"; down_revision="0001_mandate_state"; branch_labels=None; depends_on=None
def upgrade():
    op.add_column("acquisition_tasks",sa.Column("attempt_count",sa.Integer(),nullable=False,server_default="0")); op.add_column("acquisition_tasks",sa.Column("started_at",sa.DateTime(timezone=True))); op.add_column("acquisition_tasks",sa.Column("completed_at",sa.DateTime(timezone=True))); op.add_column("acquisition_tasks",sa.Column("failure_code",sa.String(100))); op.add_column("acquisition_tasks",sa.Column("created_at",sa.DateTime(timezone=True),server_default=sa.text("now()"),nullable=False))
    op.create_table("telegraph_calls",sa.Column("telegraph_call_id",sa.String(36),primary_key=True),sa.Column("mandate_id",sa.String(36),sa.ForeignKey("mandates.mandate_id"),nullable=False),sa.Column("acquisition_id",sa.String(36),sa.ForeignKey("acquisition_tasks.acquisition_id"),nullable=False,unique=True),sa.Column("causal_request_id",sa.String(36),nullable=False),sa.Column("miner_id",sa.String(255)),sa.Column("miner_name",sa.String(255)),sa.Column("intent",sa.String(255)),sa.Column("signal_hash",sa.String(255)),sa.Column("cost_usd",sa.Numeric(18,6)),sa.Column("duration_ms",sa.Integer()),sa.Column("reasoning",sa.Text()),sa.Column("warnings",postgresql.JSONB(),nullable=False),sa.Column("raw_response",postgresql.JSONB(),nullable=False),sa.Column("status",sa.String(32),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False),sa.Column("completed_at",sa.DateTime(timezone=True)))
    op.create_table("usage_events",sa.Column("event_id",sa.String(36),primary_key=True),sa.Column("mandate_id",sa.String(36),sa.ForeignKey("mandates.mandate_id"),nullable=False),sa.Column("acquisition_id",sa.String(36)),sa.Column("event_type",sa.String(64),nullable=False),sa.Column("metadata",postgresql.JSONB(),nullable=False),sa.Column("created_at",sa.DateTime(timezone=True),nullable=False))
def downgrade(): op.drop_table("usage_events"); op.drop_table("telegraph_calls")
