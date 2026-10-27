"""Tool: get_native_balance – Get native ETH balance of an address."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class GetNativeBalanceInput(BaseModel):
    address: str = Field(description="Ethereum address (0x-prefixed, 42 chars)")


@register_tool
class GetNativeBalance(BaseTool):
    name = "get_native_balance"
    description = "Get the native ETH balance of an address on Sepolia testnet. Returns balance in both wei and ETH."
    risk_level = RiskLevel.READ
    args_schema = GetNativeBalanceInput

    async def run(self, validated: GetNativeBalanceInput, ctx: ToolContext) -> ToolResult:
        try:
            balance_wei = await ctx.blockchain.get_balance(validated.address)
            balance_eth = balance_wei / 10**18
            return ToolResult.success({
                "address": validated.address,
                "balance_wei": str(balance_wei),
                "balance_eth": f"{balance_eth:.6f}",
                "unit": "ETH (Sepolia)",
            })
        except Exception as e:
            return ToolResult.failure(f"Failed to get balance: {e}")
