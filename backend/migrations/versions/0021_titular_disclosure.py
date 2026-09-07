"""Protect disclosure events in UsageEvent; no new table or Ticket mutation."""
from alembic import op

revision = "0021_titular_disclosure"
down_revision = "0020_user_credit"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE FUNCTION protect_titular_disclosure() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'TRUNCATE' THEN
            IF EXISTS (SELECT 1 FROM usage_events WHERE metadata->>'schema_version' = 'titular-disclosure-v0') THEN
              RAISE EXCEPTION 'disclosure events are append-only';
            END IF;
            RETURN NULL;
          END IF;
          IF OLD.metadata->>'schema_version' = 'titular-disclosure-v0' THEN
            RAISE EXCEPTION 'disclosure events are append-only';
          END IF;
          IF TG_OP = 'UPDATE' AND NEW.metadata->>'schema_version' = 'titular-disclosure-v0' THEN
            RAISE EXCEPTION 'disclosure events must be inserted';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("CREATE TRIGGER titular_disclosure_immutable BEFORE UPDATE OR DELETE ON usage_events FOR EACH ROW EXECUTE FUNCTION protect_titular_disclosure()")
    op.execute("CREATE TRIGGER titular_disclosure_no_truncate BEFORE TRUNCATE ON usage_events FOR EACH STATEMENT EXECUTE FUNCTION protect_titular_disclosure()")
    op.execute("CREATE INDEX ix_usage_disclosure_identity ON usage_events ((metadata->>'agent_identity_id'), created_at) WHERE metadata->>'schema_version' = 'titular-disclosure-v0'")


def downgrade():
    raise RuntimeError("Append-only disclosure retention requires an explicit migration plan")
