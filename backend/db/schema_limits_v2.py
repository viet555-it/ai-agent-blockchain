"""Frozen additive schema for migration 0002_limits; leave schema_v1 unchanged."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Table,
)

metadata = MetaData()
scopes = Table(
    "daily_limit_scopes",
    metadata,
    Column("wallet_id", String(36), primary_key=True),
    Column("deployment_id", String(36), primary_key=True),
    Column("asset_id", String(48), primary_key=True),
    Column("version", Integer, nullable=False),
)
entries = Table(
    "daily_limit_entries",
    metadata,
    Column("reservation_id", String(128), primary_key=True),
    Column("wallet_id", String(36), nullable=False),
    Column("deployment_id", String(36), nullable=False),
    Column("asset_id", String(48), nullable=False),
    Column("amount_base_units", String(78), nullable=False),
    Column("status", String(16), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("spent_at", Float),
    ForeignKeyConstraint(
        ["wallet_id", "deployment_id", "asset_id"],
        [
            "daily_limit_scopes.wallet_id",
            "daily_limit_scopes.deployment_id",
            "daily_limit_scopes.asset_id",
        ],
    ),
    CheckConstraint("status IN ('RESERVED','SPENT','REVERTED')"),
    CheckConstraint(
        "(status = 'SPENT' AND spent_at IS NOT NULL) OR (status != 'SPENT' AND spent_at IS NULL)"
    ),
)
Index(
    "ix_daily_limit_usage",
    entries.c.wallet_id,
    entries.c.deployment_id,
    entries.c.asset_id,
    entries.c.status,
    entries.c.spent_at,
)
