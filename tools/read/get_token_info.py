"""Tool: get_token_info – Get ERC-20 token metadata."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class GetTokenInfoInput(BaseModel):
    token_address: str = Field(description="ERC-20 token contract address")


@register_tool
class GetTokenInfo(BaseTool):
    name = "get_token_info"
    description = "Get ERC-20 token metadata: name, symbol, decimals, and total supply."
    risk_level = RiskLevel.READ
    args_schema = GetTokenInfoInput

    async def run(self, validated: GetTokenInfoInput, ctx: ToolContext) -> ToolResult:
        try:
            cache_key = f"token_info:{validated.token_address}"
            cached = ctx.cache_get(cache_key)
            if cached is not None:
                return ToolResult.success(cached, source="cache")

            info = await ctx.blockchain.get_token_info(validated.token_address)
            decimals = info.get("decimals", 18)
            total_supply_raw = info.get("total_supply", 0)
            result = {
                "token_address": validated.token_address,
                "name": info.get("name", "Unknown"),
                "symbol": info.get("symbol", "???"),
                "decimals": decimals,
                "total_supply_raw": str(total_supply_raw),
                "total_supply": f"{total_supply_raw / (10 ** decimals):.2f}",
            }
            ctx.cache_set(cache_key, result)
            return ToolResult.success(result)
        except Exception as e:
            return ToolResult.failure(f"Failed to get token info: {e}")
