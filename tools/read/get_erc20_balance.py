"""Tool: get_erc20_balance – Get ERC-20 token balance."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class GetERC20BalanceInput(BaseModel):
    token_address: str = Field(description="ERC-20 token contract address")
    wallet_address: str = Field(description="Wallet address to check balance for")


@register_tool
class GetERC20Balance(BaseTool):
    name = "get_erc20_balance"
    description = "Get the ERC-20 token balance of a wallet. Returns raw balance and human-readable amount (adjusted for decimals)."
    risk_level = RiskLevel.READ
    args_schema = GetERC20BalanceInput

    async def run(self, validated: GetERC20BalanceInput, ctx: ToolContext) -> ToolResult:
        try:
            raw_balance = await ctx.blockchain.get_erc20_balance(
                validated.token_address, validated.wallet_address
            )
            # Try to get decimals for human-readable conversion
            cache_key = f"decimals:{validated.token_address}"
            decimals = ctx.cache_get(cache_key)
            if decimals is None:
                try:
                    info = await ctx.blockchain.get_token_info(validated.token_address)
                    decimals = info.get("decimals", 18)
                    ctx.cache_set(cache_key, decimals)
                except Exception:
                    decimals = 18  # fallback

            human_balance = raw_balance / (10**decimals)
            return ToolResult.success({
                "token_address": validated.token_address,
                "wallet_address": validated.wallet_address,
                "raw_balance": str(raw_balance),
                "balance": f"{human_balance:.6f}",
                "decimals": decimals,
            })
        except Exception as e:
            return ToolResult.failure(f"Failed to get ERC-20 balance: {e}")
