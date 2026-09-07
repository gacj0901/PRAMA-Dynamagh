"""Add internal credit with database-enforced append-only and balance guards."""
from alembic import op
import sqlalchemy as sa

revision = '0020_user_credit'
down_revision = '0019_shared_policy_gate'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_identities',
        sa.Column('user_id',sa.String(36),primary_key=True),
        sa.Column('email',sa.String(254),unique=True,nullable=False),
        sa.Column('password_hash',sa.String(255),nullable=False),
        sa.Column('status',sa.String(24),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint("email = lower(btrim(email))",name='ck_user_email_normalized'))
    op.create_table('user_sessions',
        sa.Column('token_hash',sa.String(64),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('user_identities.user_id'),nullable=False),
        sa.Column('expires_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('revoked_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_user_sessions_user_id','user_sessions',['user_id'])
    op.create_table('user_credit_accounts',
        sa.Column('user_id',sa.String(36),sa.ForeignKey('user_identities.user_id'),primary_key=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('user_mandates',
        sa.Column('mandate_id',sa.String(36),sa.ForeignKey('mandates.mandate_id'),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('user_credit_accounts.user_id'),nullable=False),
        sa.Column('request_key',sa.String(128),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.UniqueConstraint('user_id','request_key',name='uq_user_mandate_request'))
    op.create_index('ix_user_mandates_user_id','user_mandates',['user_id'])
    op.create_table('user_credit_ledger',
        sa.Column('event_id',sa.String(36),primary_key=True),
        sa.Column('user_id',sa.String(36),sa.ForeignKey('user_credit_accounts.user_id'),nullable=False),
        sa.Column('event_type',sa.String(32),nullable=False),
        sa.Column('amount',sa.Numeric(18,6),nullable=False),
        sa.Column('mandate_id',sa.String(36),sa.ForeignKey('user_mandates.mandate_id')),
        sa.Column('acquisition_id',sa.String(36),sa.ForeignKey('acquisition_tasks.acquisition_id')),
        sa.Column('idempotency_key',sa.String(200),unique=True,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.CheckConstraint('amount >= 0',name='ck_user_credit_nonnegative_amount'),
        sa.CheckConstraint("event_type IN ('WELCOME_CREDIT','SPEND_RESERVATION','SPEND_SETTLEMENT','RESERVATION_RELEASE')",name='ck_user_credit_event_type'),
        sa.CheckConstraint("(event_type = 'WELCOME_CREDIT' AND mandate_id IS NULL AND acquisition_id IS NULL) OR (event_type <> 'WELCOME_CREDIT' AND mandate_id IS NOT NULL)",name='ck_user_credit_event_scope'))
    op.create_index('ix_user_credit_ledger_user_id','user_credit_ledger',['user_id'])
    op.create_index('ix_user_credit_ledger_mandate_id','user_credit_ledger',['mandate_id'])
    op.create_index('uq_user_welcome_once','user_credit_ledger',['user_id'],unique=True,postgresql_where=sa.text("event_type='WELCOME_CREDIT'"))
    op.create_index('uq_user_settlement_once','user_credit_ledger',['acquisition_id'],unique=True,postgresql_where=sa.text("event_type='SPEND_SETTLEMENT'"))
    op.execute("""
        CREATE VIEW user_credit_balances AS
        SELECT a.user_id,
          coalesce(sum(l.amount) FILTER (WHERE event_type='WELCOME_CREDIT'),0) AS total_credit,
          coalesce(sum(CASE WHEN event_type='SPEND_RESERVATION' THEN amount WHEN event_type IN ('SPEND_SETTLEMENT','RESERVATION_RELEASE') THEN -amount ELSE 0 END),0) AS reserved_credit,
          coalesce(sum(l.amount) FILTER (WHERE event_type='SPEND_SETTLEMENT'),0) AS spent_credit,
          coalesce(sum(CASE WHEN event_type='WELCOME_CREDIT' THEN amount WHEN event_type='SPEND_RESERVATION' THEN -amount WHEN event_type='RESERVATION_RELEASE' THEN amount ELSE 0 END),0) AS available_credit
        FROM user_credit_accounts a LEFT JOIN user_credit_ledger l USING(user_id) GROUP BY a.user_id
    """)
    op.execute("""
        CREATE FUNCTION reject_user_credit_mutation() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'USER_CREDIT_APPEND_ONLY' USING ERRCODE='55000'; END;
        $$ LANGUAGE plpgsql
    """)
    op.execute('CREATE TRIGGER user_credit_no_mutation BEFORE UPDATE OR DELETE ON user_credit_ledger FOR EACH ROW EXECUTE FUNCTION reject_user_credit_mutation()')
    op.execute('CREATE TRIGGER user_credit_no_truncate BEFORE TRUNCATE ON user_credit_ledger FOR EACH STATEMENT EXECUTE FUNCTION reject_user_credit_mutation()')
    op.execute("""
        CREATE FUNCTION guard_user_credit_insert() RETURNS trigger AS $$
        DECLARE available numeric; held numeric; mandate_held numeric;
        BEGIN
          PERFORM user_id FROM user_credit_accounts WHERE user_id=NEW.user_id FOR UPDATE;
          IF NOT FOUND THEN RAISE EXCEPTION 'USER_ACCOUNT_MISSING'; END IF;
          IF NEW.mandate_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM user_mandates WHERE mandate_id=NEW.mandate_id AND user_id=NEW.user_id) THEN RAISE EXCEPTION 'USER_CREDIT_LINEAGE_INVALID'; END IF;
          IF NEW.acquisition_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM acquisition_tasks WHERE acquisition_id=NEW.acquisition_id AND mandate_id=NEW.mandate_id) THEN RAISE EXCEPTION 'USER_CREDIT_ACQUISITION_INVALID'; END IF;
          SELECT available_credit,reserved_credit INTO available,held FROM user_credit_balances WHERE user_id=NEW.user_id;
          SELECT coalesce(sum(CASE WHEN event_type='SPEND_RESERVATION' THEN amount WHEN event_type IN ('SPEND_SETTLEMENT','RESERVATION_RELEASE') THEN -amount ELSE 0 END),0)
            INTO mandate_held FROM user_credit_ledger WHERE user_id=NEW.user_id AND mandate_id=NEW.mandate_id;
          IF NEW.event_type='SPEND_RESERVATION' AND NEW.amount>available THEN RAISE EXCEPTION 'USER_CREDIT_INSUFFICIENT' USING ERRCODE='23514'; END IF;
          IF NEW.event_type IN ('SPEND_SETTLEMENT','RESERVATION_RELEASE') AND (NEW.amount>held OR NEW.amount>mandate_held) THEN RAISE EXCEPTION 'USER_CREDIT_RESERVATION_EXCEEDED' USING ERRCODE='23514'; END IF;
          IF NEW.event_type='SPEND_SETTLEMENT' AND NEW.acquisition_id IS NULL THEN RAISE EXCEPTION 'USER_CREDIT_ACQUISITION_REQUIRED'; END IF;
          RETURN NEW;
        END; $$ LANGUAGE plpgsql
    """)
    op.execute('CREATE TRIGGER user_credit_balance_guard BEFORE INSERT ON user_credit_ledger FOR EACH ROW EXECUTE FUNCTION guard_user_credit_insert()')


def downgrade():
    raise RuntimeError('User credit is append-only; destructive downgrade requires an explicit retention/migration plan')
