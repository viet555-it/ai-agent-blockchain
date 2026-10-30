"""Legacy reads helpers; orchestration remains in BlockchainAgent."""

import logging
from typing import Any

logger = logging.getLogger("agent.service")


def execute_read_tool(
    blockchain, default_wallet, tool_name: str, params: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        if tool_name == "get_native_balance":
            addr = params.get("address", default_wallet)
            res = blockchain.get_native_balance(addr)
            return res, None

        if tool_name == "get_token_balance":
            addr = params.get("address", default_wallet)
            # Resolve deployed AgentToken
            _, manifest = blockchain.network_manager.load_deployment_manifest(blockchain.chain_id)
            token_addr = manifest["contractAddress"]
            res = blockchain.get_token_balance(token_addr, addr)
            return res, None

        if tool_name == "get_token_info":
            _, manifest = blockchain.network_manager.load_deployment_manifest(blockchain.chain_id)
            token_addr = manifest["contractAddress"]
            res = blockchain.get_token_info(token_addr)
            return res, None

        if tool_name == "get_gas_price":
            res = blockchain.get_gas_price()
            return res, None

        if tool_name == "simulate_transfer":
            sender = params.get("wallet", default_wallet)
            res = blockchain.simulate_transfer(
                sender=sender,
                recipient=params["recipient"],
                amount_token=params["amount"],
            )
            return res, None

        if tool_name == "get_recent_transactions":
            # Simulated recent block/tx summary for active network
            latest_block = blockchain.get_block("latest")
            return {
                "block_number": latest_block.get("number"),
                "block_hash": latest_block.get("hash", {}).hex()
                if hasattr(latest_block.get("hash"), "hex")
                else str(latest_block.get("hash")),
                "tx_count": len(latest_block.get("transactions", [])),
                "chain_id": blockchain.chain_id,
            }, None

        return None, f"Tool {tool_name} is not a recognized read operation"
    except Exception as e:
        logger.error(f"Error executing {tool_name}: {e}")
        return None, str(e)
