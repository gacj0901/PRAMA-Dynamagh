from alembic import op
revision='0005_ticket';down_revision='0004_g4_uniqueness';branch_labels=None;depends_on=None
def upgrade():
 op.execute("CREATE TABLE tickets (ticket_id varchar(36) PRIMARY KEY, mandate_id varchar(36), decision_id varchar(36), schema_version varchar(64), canonical_payload jsonb, ticket_hash varchar(66) UNIQUE, hash_algorithm varchar(32), anchor_status varchar(32), chain_id integer, contract_address varchar(255), tx_hash varchar(255), block_number integer, onchain_output_hash varchar(255), created_at timestamptz, updated_at timestamptz, UNIQUE(decision_id,schema_version))")
def downgrade(): op.execute('DROP TABLE tickets')
