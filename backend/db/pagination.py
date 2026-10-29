"""Stable timestamp/id keyset pagination shared by history and wallet queries."""

import base64

from sqlalchemy import and_, or_

from backend.services.wallet_common import fail


def encode_cursor(timestamp, record_id):
    return base64.urlsafe_b64encode(f"{timestamp}|{record_id}".encode()).decode()


def page(connection, statement, table, timestamp, cursor=None, limit=30):
    if cursor:
        try:
            value, record_id = base64.urlsafe_b64decode(cursor.encode()).decode().split("|", 1)
            value = float(value)
        except Exception:
            fail(400, "CURSOR", "Invalid history cursor.")
        statement = statement.where(
            or_(timestamp < value, and_(timestamp == value, table.c.id < record_id))
        )
    rows = [
        dict(row)
        for row in connection.execute(
            statement.order_by(timestamp.desc(), table.c.id.desc()).limit(limit + 1)
        ).mappings()
    ]
    more, rows = (len(rows) > limit, rows[:limit])
    return {
        "items": rows,
        "next_cursor": encode_cursor(rows[-1][timestamp.name], rows[-1]["id"]) if more else None,
    }
