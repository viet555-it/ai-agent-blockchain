"""Legacy validation helpers; orchestration remains in BlockchainAgent."""

from typing import Any


def validate_parameters(
    blockchain, default_wallet, tool_name: str, raw_params: dict[str, Any]
) -> tuple[bool, str | None, dict[str, Any]]:
    clean = dict(raw_params)
    wallet = raw_params.get("target_address") or raw_params.get("wallet")

    if tool_name in ("get_native_balance", "get_token_balance"):
        if not wallet or not blockchain.validate_and_checksum_address(wallet):
            return False, f"Invalid wallet address: {wallet}", clean
        clean["address"] = blockchain.validate_and_checksum_address(wallet)
        return True, None, clean

    if tool_name == "get_token_info":
        # Use configured AgentToken deployment if none provided
        return True, None, clean

    if tool_name == "get_gas_price":
        return True, None, clean

    if tool_name in ("erc20_transfer", "native_transfer"):
        recipient = raw_params.get("target_address") or raw_params.get("second_address")
        if not recipient:
            return (
                False,
                "Recipient address is required for transfers. (e.g., 'Transfer 50 AGNT to 0x...')",
                clean,
            )
        clean["recipient"] = recipient
        amount = raw_params.get("amount")
        if not amount:
            return False, "Transfer amount is required.", clean
        clean["amount"] = amount
        clean["token_symbol"] = "ETH" if tool_name == "native_transfer" else "AGNT"
        return True, None, clean

    if tool_name == "faucet_claim":
        clean["recipient"] = wallet
        clean["amount"] = raw_params.get("amount", "100")
        return True, None, clean

    if tool_name == "simulate_transfer":
        recipient = raw_params.get("target_address") or raw_params.get("second_address")
        clean["recipient"] = recipient or default_wallet
        clean["amount"] = raw_params.get("amount", "10")
        return True, None, clean

    return True, None, clean
