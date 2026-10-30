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

    if not recipient_addr:
        violations.append("Recipient address is required.")
    if amount_raw is None:
        violations.append("Transaction amount is required.")

    if recipient_addr:
        is_valid_addr, checksum_recipient, err = address_validator(recipient_addr, "recipient")
        if not is_valid_addr:
            violations.append(err or "Invalid recipient address")
        else:
            sanitized_params["recipient"] = checksum_recipient
            if int(checksum_recipient, 16) == 0:
                violations.append("Zero recipient address is not permitted.")
            # Whitelist Check
            if config.enforce_whitelist and checksum_recipient not in normalized_whitelist:
                violations.append(
                    f"Recipient address {checksum_recipient} is NOT in the authorized whitelist."
                )

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
