"""Backend READ adapters and an isolated registry of proposal-only tools."""

import asyncio
from typing import Any

from tools.base import BaseTool, RiskLevel, ToolResult
from tools.registry import ToolRegistry


def json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value


class BackendReadTool(BaseTool):
    risk_level = RiskLevel.READ

    def __init__(self, template: BaseTool, service: Any):
        self.name = template.name
        self.description = template.description.replace("Sepolia", "the configured network")
        self.args_schema = template.args_schema
        self.service = service

    async def run(self, validated: Any, ctx: Any) -> ToolResult:
        params = validated.model_dump()
        if self.name == "get_block" and params.get("block_identifier", "").isdigit():
            params["block_identifier"] = int(params["block_identifier"])

        if self.name == "get_token_price":
            try:
                from services.price_service import PriceService

                price_service = getattr(self.service, "_price_service", None)
                if not isinstance(price_service, PriceService):
                    rpc_url = getattr(self.service, "rpc_url", None)
                    price_service = PriceService(rpc_url=rpc_url)
                    try:
                        self.service._price_service = price_service
                    except Exception:
                        pass
                symbol = (params.get("symbol") or "ETH").upper()
                tf = (params.get("timeframe") or "24h").lower()
                src = (params.get("source") or "coingecko").lower()
                result = await price_service.get_token_price(symbol=symbol, timeframe=tf, source=src)
                return ToolResult.success(json_value(result))
            except Exception:
                return ToolResult.failure("Token price read failed; check provider and parameters.")

        methods = {
            "get_native_balance": "get_native_balance",
            "get_erc20_balance": "get_token_balance",
            "get_token_info": "get_token_info",
            "get_gas_price": "get_gas_price",
            "get_block": "get_block",
            "get_transaction": "get_transaction",
        }
        try:
            result = await asyncio.to_thread(getattr(self.service, methods[self.name]), **params)
            if self.name == "get_transaction":
                fields = (
                    "hash",
                    "from",
                    "to",
                    "nonce",
                    "blockHash",
                    "blockNumber",
                    "transactionIndex",
                    "value",
                    "value_eth",
                    "gas",
                    "gasPrice",
                    "maxFeePerGas",
                    "maxPriorityFeePerGas",
                    "chainId",
                    "type",
                )
                result = {key: result[key] for key in fields if key in result}
            return ToolResult.success(json_value(result))
        except Exception:
            return ToolResult.failure("Blockchain read failed; check RPC and request parameters.")


class BackendReadRegistry(ToolRegistry):
    """Private snapshot: no global WRITE tools can become executable here."""

    def __init__(self, service: Any, transactions: Any = None):
        from tools.read.get_block import GetBlock
        from tools.read.get_erc20_balance import GetERC20Balance
        from tools.read.get_gas_price import GetGasPrice
        from tools.read.get_native_balance import GetNativeBalance
        from tools.read.get_token_info import GetTokenInfo
        from tools.read.get_token_price import GetTokenPrice
        from tools.read.get_transaction import GetTransaction

        super().__init__(enabled_override=[])
        templates = [
            GetNativeBalance,
            GetERC20Balance,
            GetTokenInfo,
            GetGasPrice,
            GetBlock,
            GetTransaction,
            GetTokenPrice,
        ]
        self._reads = {cls.name: BackendReadTool(cls(), service) for cls in templates}
        if transactions is not None:
            from backend.agent.proposal_tools import proposal_tools

            self._reads.update(proposal_tools(transactions))

    def get(self, name: str) -> BaseTool | None:
        return self._reads.get(name)

    def all_tools(self) -> dict[str, BaseTool]:
        return dict(self._reads)
