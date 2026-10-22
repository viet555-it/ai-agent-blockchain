"""Tool: transfer_eth – Transfer native ETH on Sepolia."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class TransferEthInput(BaseModel):
    to: str = Field(description="Recipient address (0x-prefixed)")
    value_eth: str = Field(description="Amount of ETH to send (e.g. '0.01')")


@register_tool
class TransferEth(BaseTool):
    name = "transfer_eth"
    description = (
        "Transfer native ETH to an address on Sepolia testnet. "
        "REQUIRES user confirmation. Subject to guardrail policy checks."
    )
    risk_level = RiskLevel.WRITE
    args_schema = TransferEthInput

    async def run(self, validated: TransferEthInput, ctx: ToolContext) -> ToolResult:
        try:
            value_eth = float(validated.value_eth)
            value_wei = int(value_eth * 10**18)

            # Policy check
            from security.policy import PolicyEngine

            policy = PolicyEngine()
            decision = policy.check_transfer(validated.to, value_eth)
            if not decision.allowed:
                return ToolResult.failure(
                    f"Policy blocked: {decision.reason}",
                    code="POLICY_DENIED",
                )

            # Dry-run mode
            if ctx.settings.dry_run:
                # Estimate gas for preview
                gas_est = await ctx.blockchain.estimate_gas({
                    "to": validated.to,
                    "value": value_wei,
                })
                gas_price = await ctx.blockchain.get_gas_price()
                cost_eth = (gas_est * gas_price) / 10**18

                return ToolResult.success({
                    "status": "DRY_RUN",
                    "message": "Transaction NOT sent (dry_run=true). Preview below.",
                    "to": validated.to,
                    "value_eth": validated.value_eth,
                    "estimated_gas": gas_est,
                    "estimated_cost_eth": f"{cost_eth:.8f}",
                })

            # Real transaction
            nonce = await ctx.blockchain.get_transaction_count(
                ctx.settings.wallet_private_key[:42]  # derive from key
            )
            gas_price = await ctx.blockchain.get_gas_price()
            chain_id = await ctx.blockchain.get_chain_id()

            # Build, sign, and send transaction
            from eth_account import Account

            tx = {
                "to": validated.to,
                "value": value_wei,
                "gas": 21000,
                "gasPrice": gas_price,
                "nonce": nonce,
                "chainId": chain_id,
            }
            signed = Account.sign_transaction(tx, ctx.settings.wallet_private_key)
            tx_hash = await ctx.blockchain.send_raw_transaction(signed.raw_transaction)

            # Record usage for daily limit
            policy.record_usage(value_eth)

            return ToolResult.success({
                "status": "SENT",
                "tx_hash": tx_hash,
                "to": validated.to,
                "value_eth": validated.value_eth,
            })
        except Exception as e:
            return ToolResult.failure(f"Transfer failed: {e}")
