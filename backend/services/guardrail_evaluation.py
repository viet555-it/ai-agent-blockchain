"""Read-only policy preview for the wallet-policy API integration.

The caller supplies an authenticated scope and server-owned config/token metadata
in one consistent read transaction. This function grants no signing permission.
"""

from web3 import Web3

from backend.guardrail.rules import check_recipient
from backend.services.daily_limits import WINDOW_SECONDS, DailyLimitService, amount_units, timestamp
from backend.services.transactions.serialization import digest
from backend.services.wallet.limits import transfer_limit_request


def evaluate_transfer_policy(
    connection,
    *,
    scope,
    config,
    operation,
    recipient,
    amount_base_units,
    now,
    known_token_decimals=None,
    policy_version=None,
):
    """Evaluate stored policy plus usage without proposals, approvals, audit or reservations.

    ``config``, ``scope``, ``policy_version`` and ``known_token_decimals`` must come
    from trusted server state, never from a client's claimed policy or usage.
    None version explicitly identifies the current runtime-only configuration.
    Database/configuration failures propagate instead of becoming policy blocks.
    """
    scope.values()
    timestamp(now)
    if policy_version is not None and (type(policy_version) is not int or policy_version < 1):
        raise ValueError("Policy version must be a positive server-owned integer or None")
    config = config.model_copy(deep=True)
    result = {
        "decision": "BLOCK",
        "reason_code": None,
        "violations": [],
        "policy_version": policy_version,
        "policy_hash": digest(config.model_dump(mode="json")),
        "operation": operation,
        "asset_id": scope.asset_id,
        "recipient": None,
        "per_tx_limit_base_units": None,
        "daily_limit_base_units": None,
        "spent_base_units": None,
        "reserved_base_units": None,
        "requested_base_units": None,
        "remaining_base_units": None,
        "as_of": now,
        "window_seconds": WINDOW_SECONDS,
        "checks_scope": "policy_only",
    }

    def block(code):
        result["violations"].append(code)
        result["reason_code"] = result["violations"][0]
        return result

    if operation not in {"native_transfer", "erc20_transfer"}:
        return block("UNSUPPORTED_OPERATION")
    native = operation == "native_transfer"
    if native != (scope.asset_id == "native"):
        return block("OPERATION_ASSET_MISMATCH")
    try:
        amount = amount_units(amount_base_units, positive=True)
    except ValueError:
        return block("INVALID_AMOUNT")
    result["requested_base_units"] = str(amount)
    whitelist = {
        Web3.to_checksum_address(address)
        for address in config.recipient_whitelist
        if Web3.is_address(address)
    }
    normalized, codes, _ = check_recipient(recipient, config.enforce_whitelist, whitelist)
    result["recipient"] = normalized
    result["violations"].extend(codes)
    parameters = {"raw_amount": str(amount)}
    if not native:
        metadata = dict(known_token_decimals or {})
        if scope.asset_id not in metadata:
            return block("ASSET_POLICY_MISSING")
        parameters.update(
            contract_address=scope.asset_id.removeprefix("erc20:"),
            token_decimals=metadata[scope.asset_id],
        )
    request = transfer_limit_request(
        scope.wallet_id, scope.deployment_id, operation, parameters, config
    )
    limit = DailyLimitService.evaluate(connection, **request, now=now)
    result.update(
        per_tx_limit_base_units=str(request["per_tx_limit"]),
        daily_limit_base_units=str(request["daily_limit"]),
        spent_base_units=str(limit.spent),
        reserved_base_units=str(limit.reserved),
        remaining_base_units=str(limit.remaining),
    )
    if amount > request["per_tx_limit"]:
        result["violations"].append("PER_TX_LIMIT_EXCEEDED")
    if amount > limit.remaining:
        result["violations"].append("DAILY_LIMIT_EXCEEDED")
    if result["violations"]:
        result["reason_code"] = result["violations"][0]
    elif config.require_human_approval_for_writes:
        result.update(decision="REQUIRE_APPROVAL", reason_code="APP_APPROVAL_REQUIRED")
    else:
        result.update(decision="ALLOW", reason_code="POLICY_OK")
    return result
