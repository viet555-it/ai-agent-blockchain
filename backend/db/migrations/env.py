"""Use the explicit connection supplied by the application migration command."""

from alembic import context

from backend.db.schema_v1 import metadata

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use python -m scripts.migrate_app_db")
context.configure(
    connection=connection,
    target_metadata=metadata,
    render_as_batch=connection.dialect.name == "sqlite",
)
with context.begin_transaction():
    context.run_migrations()
