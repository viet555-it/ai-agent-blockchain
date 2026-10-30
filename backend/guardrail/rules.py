"""Guardrail validation rules and operation sets."""

import hashlib
import json
import re
from typing import Any

from web3 import Web3

from backend.guardrail.models import PolicyConfig

READ_OPERATIONS = {
    "get_block",
    "get_recent_transactions",
    "get_erc20_balance",
    "get_native_balance",
    "get_token_balance",
    "get_token_info",
    "get_allowance",
    "get_transaction",
    "get_transaction_receipt",
    "get_gas_price",
    "read_contract",
    "simulate_transfer",
    "get_crypto_price",
}


WRITE_OPERATIONS = {
    "native_transfer",
    "erc20_transfer",
    "faucet_claim",
    "contract_write",
    "call_contract",
}


def compute_parameter_hash(operation: str, parameters: dict[str, Any]) -> str:
    serialized = json.dumps({"op": operation, "params": parameters}, sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()


def format_description(operation: str, params: dict[str, Any]) -> str:
    if operation == "erc20_transfer":
        return f"Transfer {params.get('amount', '?')} AGNT to {params.get('recipient', '?')}"
    if operation == "native_transfer":
        return f"Transfer {params.get('amount', '?')} ETH to {params.get('recipient', '?')}"
    if operation == "faucet_claim":
        return f"Claim tokens from faucet for {params.get('recipient', '?')}"
    return f"{operation} with params: {params}"


def validate_address(address: str) -> tuple[bool, str]:
    if not address or not isinstance(address, str):
        return False, "Address must be a non-empty string"
    if not re.match(r"^0x[a-fA-F0-9]{40}$", address):
        return False, "Address does not match 20-byte hex format (0x + 40 hex chars)"
    try:
        checksummed = Web3.to_checksum_address(address)
        return True, checksummed
    except ValueError as e:
        return False, f"Invalid checksum: {e}"


def check_write_request(
    operation: str,
    parameters: dict[str, Any],
    config: PolicyConfig,
    normalized_whitelist: set[str],
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    checks = []
    violations = []

    # 1. Check if write operations are enabled
    if not config.allow_write_operations:
        violations.append("Write operations are globally disabled by guardrail policy")
        checks.append({"check": "writes_enabled", "passed": False})
        return False, violations, checks
    checks.append({"check": "writes_enabled", "passed": True})

    # 2. Whitelist recipient validation (only for transfers)
    if operation in ("erc20_transfer", "native_transfer"):
        recipient = parameters.get("recipient", "")
        valid_format, result = validate_address(recipient)
        if not valid_format:
            violations.append(f"Recipient address validation failed: {result}")
            checks.append({"check": "recipient_valid_format", "passed": False})
        else:
            checks.append({"check": "recipient_valid_format", "passed": True})
            if config.enforce_whitelist:
                if result.lower() not in normalized_whitelist:
                    violations.append(
                        f"Recipient {result} is not on the approved destination whitelist"
                    )
                    checks.append({"check": "whitelist_enforced", "passed": False})
                else:
                    checks.append({"check": "whitelist_enforced", "passed": True})

    # 3. Limit validation
    amount_str = parameters.get("amount")
    if amount_str is not None:
        try:
            amount = float(amount_str)
            if amount <= 0:
                violations.append("Transfer amount must be strictly greater than 0")
                checks.append({"check": "amount_positive", "passed": False})
            else:
                checks.append({"check": "amount_positive", "passed": True})

            if operation == "erc20_transfer" and amount > config.max_erc20_transfer_amount:
                violations.append(
                    f"Transfer amount {amount} AGNT exceeds maximum single-tx limit of {config.max_erc20_transfer_amount} AGNT"
                )
                checks.append({"check": "max_erc20_limit", "passed": False})
            elif operation == "erc20_transfer":
                checks.append({"check": "max_erc20_limit", "passed": True})

            if operation == "native_transfer" and amount > config.max_native_transfer_amount:
                violations.append(
                    f"Transfer amount {amount} ETH exceeds maximum single-tx limit of {config.max_native_transfer_amount} ETH"
                )
                checks.append({"check": "max_native_limit", "passed": False})
            elif operation == "native_transfer":
                checks.append({"check": "max_native_limit", "passed": True})
        except (ValueError, TypeError):
            violations.append(f"Invalid transfer amount format: {amount_str}")
            checks.append({"check": "amount_numeric", "passed": False})

    is_allowed = len(violations) == 0
    return is_allowed, violations, checks
