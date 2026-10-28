"""Create a consistent SQLite snapshot, including committed WAL data; never overwrite."""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

from backend.wallet_settings import WalletSettings
from config.environment import load_project_env


def backup(database_url, output):
    url = make_url(database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise ValueError("This backup command supports SQLite files only")
    source = Path(url.database).resolve()
    destination = Path(output).resolve()
    if destination == source or destination.exists():
        raise ValueError("Choose a new backup file; existing files are never overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # URI mode=ro prevents accidentally creating an empty source database.
    with (
        closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as incoming,
        closing(sqlite3.connect(destination)) as outgoing,
    ):
        incoming.backup(outgoing)
        if outgoing.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
    return destination


def main():
    load_project_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    backup(WalletSettings.from_environment().database_url, arguments.output)
    print("SQLite backup created and integrity checked.")


if __name__ == "__main__":
    main()
