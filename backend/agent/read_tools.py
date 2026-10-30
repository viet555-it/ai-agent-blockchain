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
        if self.name == "get_block" and params["block_identifier"].isdigit():
            params["block_identifier"] = int(params["block_identifier"])
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
                # Deployment calldata and signatures can exceed the entire chat
                # budget. Keep authoritative transaction details, not raw bytecode.
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
            # Preserve exact backend decimal strings and raw integers; no float conversion.
            return ToolResult.success(json_value(result))
        except Exception:
            # RPC URLs can contain credentials. Do not echo provider exception text to the model/UI.
            return ToolResult.failure("Blockchain read failed; check RPC and request parameters.")


class BackendReadRegistry(ToolRegistry):
    """Private snapshot: no global WRITE tools can become executable here."""

    def __init__(self, service: Any, transactions: Any = None):
        from tools.read.get_block import GetBlock
        from tools.read.get_erc20_balance import GetERC20Balance
        from tools.read.get_gas_price import GetGasPrice
        from tools.read.get_native_balance import GetNativeBalance
        from tools.read.get_token_info import GetTokenInfo
        from tools.read.get_transaction import GetTransaction

        super().__init__(enabled_override=[])
        templates = [
            GetNativeBalance,
            GetERC20Balance,
            GetTokenInfo,
            GetGasPrice,
            GetBlock,
            GetTransaction,
        ]
        self._reads = {cls.name: BackendReadTool(cls(), service) for cls in templates}
        if transactions is not None:
            from backend.agent.proposal_tools import proposal_tools

            self._reads.update(proposal_tools(transactions))

    def get(self, name: str) -> BaseTool | None:
        return self._reads.get(name)

    def all_tools(self) -> dict[str, BaseTool]:
        return dict(self._reads)
