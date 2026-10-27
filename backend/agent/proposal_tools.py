"""Proposal tools never execute the legacy tool signers or grant approval."""

import asyncio
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.services.transaction_coordinator import TransactionError
from tools.base import BaseTool, RiskLevel, ToolResult


class NativeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    to: str = Field(description="Recipient wallet address")
    value_eth: str = Field(description="Exact positive ETH amount as a decimal string")


class TokenInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    to: str = Field(description="Recipient wallet address")
    amount: str = Field(description="Exact positive AGNT amount as a decimal string")
    token_address: str | None = Field(
        default=None, description="Configured AgentToken contract; omit to use active deployment"
    )


class FaucetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    amount: str = Field(
        default="100", description="AGNT to request for the configured sender; maximum 100"
    )


class ProposalTool(BaseTool):
    risk_level = RiskLevel.WRITE

    def __init__(self, name: str, operation: str, schema: type[BaseModel], coordinator: Any):
        self.name = name
        self.operation = operation
        self.args_schema = schema
        self.coordinator = coordinator
        self.description = f"Prepare a {operation} proposal on the configured chain. NEVER sends transactions. User must review and approve in the UI."

    async def run(self, validated: Any, ctx: Any) -> ToolResult:
        context = ctx.request_context
        decisions = context.get("proposal_results")
        if decisions is None or decisions:
            return ToolResult.failure("Only one transaction proposal is allowed per message")
        values = validated.model_dump()
        params = {
            "amount": values.get("value_eth", values.get("amount")),
            "recipient": values.get("to"),
            "token_address": values.get("token_address"),
            "session_id": context["session_id"],
            "actor_wallet": context["wallet"],
        }
        try:
            decision = await asyncio.to_thread(self.coordinator.propose, self.operation, **params)
        except TransactionError as error:
            return ToolResult.failure(str(error))
        except Exception:
            return ToolResult.failure("Proposal unavailable; check local network and deployment")
        decisions.append(decision)
        # Approval IDs, full payload and UI authorization remain server-side, outside LLM context.
        return ToolResult.success(
            {
                "status": "PENDING_APPROVAL" if decision.requires_approval else "BLOCKED",
                "operation": self.operation,
                "message": "No transaction has been sent",
                "violations": decision.violations,
            }
        )


def proposal_tools(coordinator: Any) -> dict[str, BaseTool]:
    return {
        name: ProposalTool(name, operation, schema, coordinator)
        for name, operation, schema in (
            ("transfer_eth", "native_transfer", NativeInput),
            ("transfer_erc20", "erc20_transfer", TokenInput),
            ("faucet_claim", "faucet_claim", FaucetInput),
        )
    }
