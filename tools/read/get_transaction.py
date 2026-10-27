"""Tool: get_transaction – Get transaction details by hash."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class GetTransactionInput(BaseModel):
    tx_hash: str = Field(description="Transaction hash (0x-prefixed, 66 chars)")


@register_tool
class GetTransaction(BaseTool):
    name = "get_transaction"
    description = "Get detailed information about a transaction by its hash, including from/to addresses, value, gas, and block number."
    risk_level = RiskLevel.READ
    args_schema = GetTransactionInput

    async def run(self, validated: GetTransactionInput, ctx: ToolContext) -> ToolResult:
        try:
            tx = await ctx.blockchain.get_transaction(validated.tx_hash)
            value_wei = tx.get("value", 0)
            if isinstance(value_wei, int):
                value_eth = value_wei / 10**18
            else:
                value_eth = int(value_wei, 16) / 10**18 if isinstance(value_wei, str) else 0

            return ToolResult.success({
                "hash": validated.tx_hash,
                "from": tx.get("from", ""),
                "to": tx.get("to", ""),
                "value_wei": str(value_wei),
                "value_eth": f"{value_eth:.6f}",
                "gas": tx.get("gas", 0),
                "gas_price": str(tx.get("gasPrice", tx.get("gas_price", 0))),
                "block_number": tx.get("blockNumber", tx.get("block_number", None)),
                "status": "confirmed" if tx.get("blockNumber") or tx.get("block_number") else "pending",
            })
        except Exception as e:
            return ToolResult.failure(f"Failed to get transaction: {e}")
