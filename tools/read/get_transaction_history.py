"""Tool: get_transaction_history – Get transaction history for an address.

Uses Etherscan Sepolia API (free tier). Requires ETHERSCAN_API_KEY.
If not configured, returns a structured error – agent continues normally.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class GetTransactionHistoryInput(BaseModel):
    address: str = Field(description="Ethereum address to get history for")
    limit: int = Field(default=10, ge=1, le=100, description="Max transactions to return (1-100)")


@register_tool
class GetTransactionHistory(BaseTool):
    name = "get_transaction_history"
    description = (
        "Get recent transaction history for an address on Sepolia. "
        "Requires ETHERSCAN_API_KEY to be configured. "
        "Returns up to 100 most recent transactions."
    )
    risk_level = RiskLevel.READ
    args_schema = GetTransactionHistoryInput

    async def run(self, validated: GetTransactionHistoryInput, ctx: ToolContext) -> ToolResult:
        try:
            api_key = ctx.settings.etherscan_api_key
            if not api_key:
                return ToolResult.failure(
                    "Transaction history is not available: ETHERSCAN_API_KEY is not configured. "
                    "Ask the user to set ETHERSCAN_API_KEY in their .env file.",
                    code="NOT_CONFIGURED",
                )

            from services.etherscan import EtherscanClient

            client = EtherscanClient(api_key)
            txs = await client.get_transactions(
                validated.address, limit=validated.limit
            )

            simplified = []
            for tx in txs[: validated.limit]:
                value_wei = int(tx.get("value", "0"))
                simplified.append({
                    "hash": tx.get("hash", ""),
                    "from": tx.get("from", ""),
                    "to": tx.get("to", ""),
                    "value_eth": f"{value_wei / 10**18:.6f}",
                    "block": tx.get("blockNumber", ""),
                    "timestamp": tx.get("timeStamp", ""),
                    "is_error": tx.get("isError", "0") == "1",
                })

            return ToolResult.success({
                "address": validated.address,
                "count": len(simplified),
                "transactions": simplified,
            })
        except Exception as e:
            return ToolResult.failure(f"Failed to get transaction history: {e}")
