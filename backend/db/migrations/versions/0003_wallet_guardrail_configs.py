"""Persist per-wallet guardrail configuration, token limits, whitelist, and approval flags."""

from alembic import op

from backend.db.schema_guardrails_v3 import metadata

revision = "0003_guardrails"
down_revision = "0002_limits"
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    metadata.drop_all(op.get_bind())

