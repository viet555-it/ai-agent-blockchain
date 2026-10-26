"""Tool: get_block – Get block information."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class GetBlockInput(BaseModel):
    block_identifier: str = Field(
        default="latest",
        description="Block number (integer as string) or 'latest'/'earliest'/'pending'",
    )


@register_tool
class GetBlock(BaseTool):
    name = "get_block"
    description = "Get information about a specific block by number or tag (latest, earliest, pending)."
    risk_level = RiskLevel.READ
    args_schema = GetBlockInput

    async def run(self, validated: GetBlockInput, ctx: ToolContext) -> ToolResult:
        try:
            bid = validated.block_identifier
            block_id: int | str = int(bid) if bid.isdigit() else bid

            block = await ctx.blockchain.get_block(block_id)
            return ToolResult.success({
                "number": block.get("number"),
                "timestamp": block.get("timestamp"),
                "transactions_count": len(block.get("transactions", [])),
                "gas_used": block.get("gasUsed", block.get("gas_used", 0)),
                "gas_limit": block.get("gasLimit", block.get("gas_limit", 0)),
            })
        except Exception as e:
            return ToolResult.failure(f"Failed to get block: {e}")
