"""Short SQLAlchemy units of work; no network calls while a DB transaction is open."""

from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]


class Database:
    def __init__(self, url):
        options = {}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 5}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine, "connect")
            def configure(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=5000")
                connection.execute("PRAGMA journal_mode=WAL")

    def migrate(self):
        config = Config(str(ROOT / "alembic.ini"))
        config.set_main_option("script_location", str(ROOT / "backend/db/migrations"))
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def check_schema(self):
        from sqlalchemy import text

        if "alembic_version" not in inspect(self.engine).get_table_names():
            raise RuntimeError(
                "Run python -m scripts.migrate_app_db before enabling wallet history"
            )
        with self.engine.connect() as connection:
            if (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
                != "0001"
            ):
                raise RuntimeError("Application database schema is not supported")

    @contextmanager
    def transaction(self):
        with self.engine.begin() as connection:
            yield connection

    def close(self):
        self.engine.dispose()
