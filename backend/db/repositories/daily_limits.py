"""SQLite ledger operations; callers own the transaction and lock before writing."""

from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.sqlite import insert

from backend.db.rows import one
from backend.db.schema_limits_v2 import entries, scopes


def scope_filter(table, scope):
    return and_(*(table.c[key] == value for key, value in scope.items()))


def lock_scope(connection, scope):
    if connection.dialect.name != "sqlite":
        raise NotImplementedError("Daily limit locking currently supports SQLite only")
    # Acquire SQLite's writer lock before reading usage. Another connection must wait
    # until this transaction commits/rolls back; a Python instance lock is insufficient.
    connection.execute(insert(scopes).values(**scope, version=0).on_conflict_do_nothing())
    connection.execute(
        update(scopes).where(scope_filter(scopes, scope)).values(version=scopes.c.version + 1)
    )


def find(connection, reservation_id):
    return one(connection, select(entries).where(entries.c.reservation_id == reservation_id))


def lock_entry(connection, reservation_id):
    # Obtain the writer lock before a settlement read to avoid upgrading an old
    # SQLite read snapshot after another connection has committed.
    connection.execute(
        update(entries)
        .where(entries.c.reservation_id == reservation_id)
        .values(reservation_id=reservation_id)
    )


def usage(connection, scope, now, window_seconds):
    rows = connection.execute(
        select(entries.c.status, entries.c.amount_base_units).where(
            scope_filter(entries, scope),
            or_(
                entries.c.status == "RESERVED",
                and_(
                    entries.c.status == "SPENT",
                    entries.c.spent_at > now - window_seconds,
                    entries.c.spent_at <= now,
                ),
            ),
        )
    )
    spent = reserved = 0
    for status, amount in rows:
        if status == "SPENT":
            spent += int(amount)
        else:
            reserved += int(amount)
    return spent, reserved


def reserve(connection, scope, reservation_id, amount, now):
    connection.execute(
        entries.insert().values(
            **scope,
            reservation_id=reservation_id,
            amount_base_units=str(amount),
            created_at=now,
            status="RESERVED",
        )
    )


def settle(connection, reservation_id, status, spent_at=None):
    connection.execute(
        update(entries)
        .where(entries.c.reservation_id == reservation_id, entries.c.status == "RESERVED")
        .values(status=status, spent_at=spent_at)
    )
