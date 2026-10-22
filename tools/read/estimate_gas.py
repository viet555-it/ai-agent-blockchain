"""Tool: estimate_gas – Estimate gas for a transaction."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class EstimateGasInput(BaseModel):
    to: str = Field(description="Destination address")
    value_wei: str = Field(default="0", description="Value in wei to send (as string)")
    data: str = Field(default="0x", description="Transaction data (hex-encoded)")


@register_tool
class EstimateGas(BaseTool):
    name = "estimate_gas"
    description = "Estimate the gas required for a transaction. Useful for previewing costs before sending."
    risk_level = RiskLevel.READ
    args_schema = EstimateGasInput

    async def run(self, validated: EstimateGasInput, ctx: ToolContext) -> ToolResult:
        try:
            tx = {
                "to": validated.to,
                "value": int(validated.value_wei),
            }
            if validated.data and validated.data != "0x":
                tx["data"] = validated.data

            gas_estimate = await ctx.blockchain.estimate_gas(tx)
            gas_price = await ctx.blockchain.get_gas_price()
            cost_wei = gas_estimate * gas_price
            cost_eth = cost_wei / 10**18

            return ToolResult.success({
                "gas_estimate": gas_estimate,
                "gas_price_gwei": f"{gas_price / 10**9:.2f}",
                "estimated_cost_wei": str(cost_wei),
                "estimated_cost_eth": f"{cost_eth:.8f}",
            })
        except Exception as e:
            return ToolResult.failure(f"Failed to estimate gas: {e}")
