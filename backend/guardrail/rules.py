"""Pure policy checks and formatting; approval state remains in PolicyEngine."""

import hashlib
import json
import re
from decimal import Decimal
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
    "erc20_approve",
    "faucet_claim",
}


def compute_parameter_hash(operation: str, parameters: dict[str, Any]) -> str:
    """Deterministically hash parameters to prevent parameter tampering."""
    # Sanitize and sort keys
    serialized = json.dumps(
        {"op": operation, "params": parameters},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def validate_address(
    address: str, field_name: str = "address"
) -> tuple[bool, str | None, str | None]:
    """Validate EVM address and return checksummed form."""
    if not address or not isinstance(address, str):
        return False, None, f"{field_name} must be a non-empty string"
    if not Web3.is_address(address):
        return False, None, f"Invalid EVM address format for {field_name}: '{address}'"
    checksummed = Web3.to_checksum_address(address)
    return True, checksummed, None


def check_recipient(
    recipient, enforce_whitelist, normalized_whitelist, *, address_validator=validate_address
):
    """Return the shared recipient checks with stable codes and legacy display messages."""
    if not recipient:
        return None, ["INVALID_ADDRESS"], ["Recipient address is required."]
    valid, checksummed, error = address_validator(recipient, "recipient")
    if not valid:
        return None, ["INVALID_ADDRESS"], [error or "Invalid recipient address"]
    codes, messages = [], []
    if int(checksummed, 16) == 0:
        codes.append("ZERO_ADDRESS")
        messages.append("Zero recipient address is not permitted.")
    if enforce_whitelist and checksummed not in normalized_whitelist:
        codes.append("RECIPIENT_NOT_ALLOWED")
        messages.append(f"Recipient address {checksummed} is NOT in the authorized whitelist.")
    return checksummed, codes, messages


def format_description(operation: str, params: dict[str, Any]) -> str:
    recipient = params.get("recipient", "N/A")
    amount = params.get("amount", params.get("amount_eth", params.get("amount_token", "N/A")))
    if operation == "native_transfer":
        return f"Send {amount} ETH to {recipient}"
    elif operation == "erc20_transfer":
        token_symbol = params.get("token_symbol", "AGNT")
        return f"Transfer {amount} {token_symbol} to {recipient}"
    elif operation == "erc20_approve":
        spender = params.get("spender", "N/A")
        token_symbol = params.get("token_symbol", "AGNT")
        return f"Approve spender {spender} for {amount} {token_symbol}"
    elif operation == "faucet_claim":
        return f"Claim {amount} AGNT testnet tokens for {recipient}"
    return f"{operation} with amount {amount}"


def check_write_request(
    operation,
    parameters,
    simulation_data,
    config: PolicyConfig,
    normalized_whitelist,
    *,
    address_validator=validate_address,
):
    sanitized_params = dict(parameters)
    violations = []
    # 3. For WRITE operations: Validate parameters
    recipient_addr = (
        parameters.get("recipient") or parameters.get("to") or parameters.get("to_address")
    )
    amount_raw = next(
        (
            parameters[k]
            for k in ("amount", "amount_eth", "amount_token")
            if k in parameters and parameters[k] is not None
        ),
        None,
    )

    checksum_recipient, _, recipient_errors = check_recipient(
        recipient_addr,
        config.enforce_whitelist,
        normalized_whitelist,
        address_validator=address_validator,
    )
    # Keep the legacy missing-field message order for existing callers.
    if not recipient_addr:
        violations.extend(recipient_errors)
    if amount_raw is None:
        violations.append("Transaction amount is required.")
    if recipient_addr:
        violations.extend(recipient_errors)
        if checksum_recipient:
            sanitized_params["recipient"] = checksum_recipient

    # 4. Amount limits check
    if amount_raw is not None:
        try:
            if type(amount_raw) not in (str, int) or not re.fullmatch(
                r"[0-9]+(?:\.[0-9]+)?", str(amount_raw)
            ):
                raise ValueError("Use a finite non-negative decimal string or integer")
            amount_dec = Decimal(str(amount_raw))
            if not amount_dec.is_finite() or amount_dec <= 0:
                violations.append("Transaction amount must be strictly greater than 0.")
            else:
                if operation == "native_transfer":
                    if amount_dec > config.max_native_transfer_limit:
                        violations.append(
                            f"Amount {amount_dec} ETH exceeds native transfer limit of {config.max_native_transfer_limit} ETH."
                        )
                elif (
                    operation in ("erc20_transfer", "erc20_approve", "faucet_claim")
                    and amount_dec > config.max_token_transfer_limit
                ):
                    violations.append(
                        f"Amount {amount_dec} tokens exceeds token policy limit of {config.max_token_transfer_limit} tokens."
                    )
        except Exception as e:
            violations.append(f"Invalid numerical amount '{amount_raw}': {e}")

    # 5. Contract dry-run simulation checks (if provided)
    if simulation_data is not None and simulation_data.get("isValid") is not True:
        reason = simulation_data.get("reason", "Simulation failed on-chain")
        violations.append(f"On-chain pre-flight simulation reverted: {reason}")

    return sanitized_params, violations
