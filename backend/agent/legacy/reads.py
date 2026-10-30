"""Legacy reads helpers; orchestration remains in BlockchainAgent."""

import asyncio
import concurrent.futures
import logging
from typing import Any

from services.price_service import PriceService

logger = logging.getLogger("agent.service")


def _run_coroutine_sync(async_fn, *args, **kwargs):
    """Run an async function synchronously inside a dedicated thread's event loop."""
    def worker():
        return asyncio.run(async_fn(*args, **kwargs))

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(worker).result()


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

        if tool_name == "get_crypto_price":
            price_service = getattr(blockchain, "_price_service", None)
            if not isinstance(price_service, PriceService):
                price_service = PriceService()
                try:
                    blockchain._price_service = price_service
                except Exception:
                    pass

            source_req = params.get("source")
            tf = params.get("timeframe", "24h")

            if source_req == "chainlink":
                chainlink_data = _run_coroutine_sync(price_service.get_chainlink_price)
                return {"type": "chainlink", "data": chainlink_data}, None

            current_data = _run_coroutine_sync(price_service.get_current_price)
            history_data = _run_coroutine_sync(price_service.get_price_history, timeframe=tf)

            return {
                "type": "coingecko",
                "current": current_data,
                "history": history_data,
                "timeframe": tf,
            }, None

        return None, f"Tool {tool_name} is not a recognized read operation"
    except Exception as e:
        logger.error(f"Error executing {tool_name}: {e}")
        return None, str(e)
