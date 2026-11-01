"""Preview legacy usage offline; explicit apply requires a reviewed snapshot and new backup."""

import argparse
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from backend.services.limit_backfill import apply_plan, build_plan
from scripts.backup_app_db import backup


@contextmanager
def database(path, *, read_only):
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError("Choose an existing SQLite database file")
    mode = "ro" if read_only else "rw"
    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(path.as_uri() + f"?mode={mode}", uri=True, timeout=5),
        poolclass=NullPool,
    )
    try:
        with engine.connect() as connection:
            if read_only:
                connection.exec_driver_sql("BEGIN")
            else:
                connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            yield connection
    finally:
        engine.dispose()


def execute(
    path, *, output, now=None, wallet_id=None, deployment_id=None, plan_path=None, backup_path=None
):
    path = Path(path).resolve()
    protected = {path, Path(str(path) + "-wal"), Path(str(path) + "-shm")}
    output_path = Path(output).resolve()
    if output_path in protected or output_path.suffix.lower() != ".json":
        raise ValueError("Choose a JSON report path outside database/sidecar files")
    if plan_path is not None and output_path == Path(plan_path).resolve():
        raise ValueError("Do not overwrite the reviewed plan")
    if backup_path is not None and (
        Path(backup_path).resolve() in protected or Path(backup_path).resolve() == output_path
    ):
        raise ValueError("Backup must be separate from database and report")
    if plan_path is None:
        with database(path, read_only=True) as connection:
            packet = build_plan(
                connection,
                now=time.time() if now is None else now,
                wallet_id=wallet_id,
                deployment_id=deployment_id,
            )
        result = packet
    else:
        if backup_path is None:
            raise ValueError("Apply requires a new --backup file")
        packet = json.loads(Path(plan_path).read_text(encoding="utf-8"))
        if (wallet_id is not None and wallet_id != packet["plan"]["wallet_id"]) or (
            deployment_id is not None and deployment_id != packet["plan"]["deployment_id"]
        ):
            raise ValueError("Apply selectors must match the reviewed plan")
        # Refuse obvious invalid plans before creating a backup or opening a writer.
        with database(path, read_only=True) as connection:
            current = build_plan(
                connection,
                now=packet["plan"]["as_of"],
                wallet_id=packet["plan"]["wallet_id"],
                deployment_id=packet["plan"]["deployment_id"],
            )
        if (
            current != packet
            or not packet["plan"]["ledger_available"]
            or packet["plan"]["counts"].get("INVALID")
        ):
            raise ValueError("Stale, invalid or unmigrated plan; preview again")
        with database(path, read_only=False) as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                locked_plan = build_plan(
                    connection,
                    now=packet["plan"]["as_of"],
                    wallet_id=packet["plan"]["wallet_id"],
                    deployment_id=packet["plan"]["deployment_id"],
                )
                if locked_plan != packet:
                    raise ValueError("Database changed before backup; preview again")
                backup("sqlite:///" + path.as_posix(), backup_path)
                result = apply_plan(connection, packet)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        result["backup"] = str(Path(backup_path).resolve())
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--wallet-id")
    parser.add_argument("--deployment-id")
    parser.add_argument("--apply-plan", help="Apply exactly this previously exported JSON preview")
    parser.add_argument("--backup", help="New SQLite backup path, mandatory when applying")
    args = parser.parse_args()
    try:
        result = execute(
            args.database,
            output=args.output,
            wallet_id=args.wallet_id,
            deployment_id=args.deployment_id,
            plan_path=args.apply_plan,
            backup_path=args.backup,
        )
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply_plan else "preview",
                "output": args.output,
                "counts": result.get("plan", {}).get("counts"),
                "imported": result.get("imported", 0),
                "requires_chain_review": result.get(
                    "requires_chain_review", result.get("plan", {}).get("requires_chain_review", [])
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
