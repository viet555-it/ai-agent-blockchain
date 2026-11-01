"""Additive schema for migration 0003_guardrails: Per-wallet Guardrail configuration."""

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
)

metadata = MetaData()

wallet_guardrail_configs = Table(
    "wallet_guardrail_configs",
    metadata,
    Column("wallet_address", String(42), primary_key=True),  # Lowercase or checksum Ethereum address
    Column("wallet_id", String(36), nullable=False, index=True),
    Column("per_tx_native_limit", String(32), nullable=False, default="0.1"),
    Column("daily_native_limit", String(32), nullable=False, default="0.5"),
    Column("token_limits", JSON, nullable=False, default=dict),
    Column("recipient_whitelist", JSON, nullable=False, default=list),
    Column("enforce_whitelist", Boolean, nullable=False, default=True),
    Column("require_app_approval", Boolean, nullable=False, default=True),
    Column("approval_timeout_seconds", Integer, nullable=False, default=600),
    Column("version", Integer, nullable=False, default=1),
    Column("updated_at", Float, nullable=False),
)

