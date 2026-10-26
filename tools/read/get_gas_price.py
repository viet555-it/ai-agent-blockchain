"""Tool: get_gas_price – Get current gas price."""

from __future__ import annotations

from pydantic import BaseModel

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class GetGasPriceInput(BaseModel):
    """No input required."""


@register_tool
class GetGasPrice(BaseTool):
    name = "get_gas_price"
    description = "Get the current gas price on Sepolia testnet in wei and gwei."
    risk_level = RiskLevel.READ
    args_schema = GetGasPriceInput

    async def run(self, validated: GetGasPriceInput, ctx: ToolContext) -> ToolResult:
        try:
            cached = ctx.cache_get("gas_price", ttl=30.0)
            if cached is not None:
                return ToolResult.success(cached, source="cache")

            gas_wei = await ctx.blockchain.get_gas_price()
            gas_gwei = gas_wei / 10**9
            result = {
                "gas_price_wei": str(gas_wei),
                "gas_price_gwei": f"{gas_gwei:.2f}",
            }
            ctx.cache_set("gas_price", result)
            return ToolResult.success(result)
        except Exception as e:
            return ToolResult.failure(f"Failed to get gas price: {e}")
