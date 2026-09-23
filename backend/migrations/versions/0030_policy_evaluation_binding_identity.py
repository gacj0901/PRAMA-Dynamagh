"""Allow append-only bound evaluations to coexist with legacy rows."""

from alembic import op


revision = "0030_eval_binding_identity"
down_revision = "0029_g13_policy_binding"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        "uq_policy_evaluations_input_identity",
        "policy_evaluations",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_policy_evaluations_input_binding_identity",
        "policy_evaluations",
        [
            "policy_id",
            "policy_version",
            "policy_type",
            "policy_subject_type",
            "policy_subject_id",
            "input_hash",
            "policy_binding_id",
        ],
    )


def downgrade():
    raise RuntimeError("Policy evaluation binding identity is append-only; destructive downgrade forbidden")
