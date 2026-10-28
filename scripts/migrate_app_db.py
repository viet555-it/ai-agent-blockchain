"""Apply app migrations explicitly, before starting the API."""

from pathlib import Path

from sqlalchemy.engine import make_url

from backend.db.store import Database
from backend.wallet_settings import WalletSettings
from config.environment import load_project_env


def main():
    load_project_env()
    settings = WalletSettings.from_environment()
    url = make_url(settings.database_url)
    if url.drivername.startswith("sqlite") and url.database and url.database != ":memory:":
        Path(url.database).resolve().parent.mkdir(parents=True, exist_ok=True)
    database = Database(settings.database_url)
    try:
        database.migrate()
        database.check_schema()
        print("Application schema is up to date (0001).")
    finally:
        database.close()


if __name__ == "__main__":
    main()
