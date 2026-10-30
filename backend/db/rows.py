"""Materialize one SQLAlchemy row as a detached dictionary."""


def one(connection, statement):
    row = connection.execute(statement).mappings().first()
    return dict(row) if row else None
