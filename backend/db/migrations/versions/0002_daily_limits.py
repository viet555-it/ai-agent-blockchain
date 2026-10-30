"""Persist daily limit reservations and settled usage."""

from alembic import op

from backend.db.schema_limits_v2 import metadata

revision = "0002_limits"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())


def downgrade():
    metadata.drop_all(op.get_bind())
