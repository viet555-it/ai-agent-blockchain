"""Repository for per-wallet Guardrail configuration."""

import time
from decimal import Decimal
from sqlalchemy import select, update
from web3 import Web3

from backend.db.rows import one
from backend.db.schema_guardrails_v3 import wallet_guardrail_configs
from backend.guardrail.models import PolicyConfig


def normalize_address(address: str) -> str:
    if not address or not Web3.is_address(address):
        return (address or "").strip().lower()
    return Web3.to_checksum_address(address)


def find_config(connection, wallet_address: str) -> dict | None:
    norm = normalize_address(wallet_address)
    row = one(
        connection,
        select(wallet_guardrail_configs).where(
            wallet_guardrail_configs.c.wallet_address == norm
        ),
    )
    if not row:
        row = one(
            connection,
            select(wallet_guardrail_configs).where(
                wallet_guardrail_configs.c.wallet_address == wallet_address.lower()
            ),
        )
    return row


def upsert_config(
    connection,
    *,
    wallet_address: str,
    wallet_id: str,
    per_tx_native_limit: str,
    daily_native_limit: str,
    token_limits: dict,
    recipient_whitelist: list[str],
    enforce_whitelist: bool,
    require_app_approval: bool,
    approval_timeout_seconds: int,
    now: float | None = None,
) -> dict:
    if now is None:
        now = time.time()
    norm = normalize_address(wallet_address)
    existing = find_config(connection, norm)

    # Normalize whitelist addresses
    normalized_whitelist = []
    for addr in recipient_whitelist:
        if Web3.is_address(addr):
            normalized_whitelist.append(Web3.to_checksum_address(addr))
        elif addr:
            normalized_whitelist.append(addr.strip())

    if existing:
        new_version = (existing.get("version") or 1) + 1
        connection.execute(
            update(wallet_guardrail_configs)
            .where(wallet_guardrail_configs.c.wallet_address == existing["wallet_address"])
            .values(
                wallet_id=wallet_id,
                per_tx_native_limit=str(per_tx_native_limit),
                daily_native_limit=str(daily_native_limit),
                token_limits=token_limits or {},
                recipient_whitelist=normalized_whitelist,
                enforce_whitelist=enforce_whitelist,
                require_app_approval=require_app_approval,
                approval_timeout_seconds=approval_timeout_seconds,
                version=new_version,
                updated_at=now,
            )
        )
    else:
        new_version = 1
        connection.execute(
            wallet_guardrail_configs.insert().values(
                wallet_address=norm,
                wallet_id=wallet_id,
                per_tx_native_limit=str(per_tx_native_limit),
                daily_native_limit=str(daily_native_limit),
                token_limits=token_limits or {},
                recipient_whitelist=normalized_whitelist,
                enforce_whitelist=enforce_whitelist,
                require_app_approval=require_app_approval,
                approval_timeout_seconds=approval_timeout_seconds,
                version=new_version,
                updated_at=now,
            )
        )
    return find_config(connection, norm)


def row_to_policy_config(row, base_config=None) -> PolicyConfig:
    cfg = base_config.model_copy(deep=True) if base_config else PolicyConfig()
    if not row:
        return cfg

    data = dict(row)
    if data.get("wallet_address"):
        cfg.wallet_address = data["wallet_address"]
    if data.get("per_tx_native_limit"):
        cfg.max_native_transfer_limit = Decimal(str(data["per_tx_native_limit"]))
    if data.get("daily_native_limit"):
        cfg.max_daily_native_transfer_limit = Decimal(str(data["daily_native_limit"]))
    if data.get("token_limits") is not None:
        cfg.token_limits = data["token_limits"] if isinstance(data["token_limits"], dict) else {}
    if data.get("recipient_whitelist") is not None:
        cfg.recipient_whitelist = list(data["recipient_whitelist"])
    if data.get("enforce_whitelist") is not None:
        cfg.enforce_whitelist = bool(data["enforce_whitelist"])
    if data.get("require_app_approval") is not None:
        cfg.require_human_approval_for_writes = bool(data["require_app_approval"])
    if data.get("approval_timeout_seconds"):
        cfg.approval_timeout_seconds = int(data["approval_timeout_seconds"])
    if data.get("version"):
        cfg.version = int(data["version"])
    return cfg
