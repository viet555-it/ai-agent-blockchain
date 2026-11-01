"""Map prepared, integrity-checked transfer parameters to a durable ledger scope."""

from backend.services.daily_limits import LimitScope, amount_units
from backend.token_amounts import to_token_units


def transfer_limit_request(wallet_id, deployment_id, operation, parameters, config):
    if operation not in {"native_transfer", "erc20_transfer"}:
        return None
    native = operation == "native_transfer"
    decimals = 18 if native else parameters["token_decimals"]
    asset = "native" if native else "erc20:" + parameters["contract_address"].lower()
    scope = LimitScope(wallet_id, deployment_id, asset)
    scope.values()
    per_tx = config.max_native_transfer_limit if native else config.max_token_transfer_limit
    daily = (
        config.max_daily_native_transfer_limit if native else config.max_daily_token_transfer_limit
    )
    return {
        "scope": scope,
        "amount": amount_units(parameters["raw_amount"], positive=True),
        "per_tx_limit": to_token_units(format(per_tx, "f"), decimals),
        "daily_limit": to_token_units(format(daily, "f"), decimals),
    }
