"""Tool: transfer_erc20 – Transfer ERC-20 tokens on Sepolia."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class TransferERC20Input(BaseModel):
    token_address: str = Field(description="ERC-20 token contract address")
    to: str = Field(description="Recipient address")
    amount: str = Field(description="Amount of tokens to send (human-readable, e.g. '100.5')")


@register_tool
class TransferERC20(BaseTool):
    name = "transfer_erc20"
    description = (
        "Transfer ERC-20 tokens to an address on Sepolia. "
        "REQUIRES user confirmation. Subject to guardrail policy checks."
    )
    risk_level = RiskLevel.WRITE
    args_schema = TransferERC20Input

    async def run(self, validated: TransferERC20Input, ctx: ToolContext) -> ToolResult:
        try:
            # Policy checks: recipient + contract
            from security.policy import PolicyEngine

            policy = PolicyEngine()

            addr_decision = policy.check_transfer(validated.to, 0.0)
            if not addr_decision.allowed:
                return ToolResult.failure(
                    f"Policy blocked: {addr_decision.reason}",
                    code="POLICY_DENIED",
                )

            contract_decision = policy.check_contract_call(
                validated.token_address, "transfer"
            )
            if not contract_decision.allowed:
                return ToolResult.failure(
                    f"Policy blocked: {contract_decision.reason}",
                    code="POLICY_DENIED",
                )

            # Get token decimals for amount conversion
            info = await ctx.blockchain.get_token_info(validated.token_address)
            decimals = info.get("decimals", 18)
            raw_amount = int(float(validated.amount) * (10**decimals))

            if ctx.settings.dry_run:
                return ToolResult.success({
                    "status": "DRY_RUN",
                    "message": "Transaction NOT sent (dry_run=true). Preview below.",
                    "token": validated.token_address,
                    "to": validated.to,
                    "amount": validated.amount,
                    "raw_amount": str(raw_amount),
                    "decimals": decimals,
                })

            # Build ERC-20 transfer call data
            from config.settings import load_abi

            abi = load_abi("erc20.json")
            # encode transfer(to, amount) call data
            from web3 import Web3

            w3 = Web3()
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(validated.token_address), abi=abi
            )
            tx_data = contract.functions.transfer(
                Web3.to_checksum_address(validated.to), raw_amount
            ).build_transaction({
                "gas": 100000,
                "gasPrice": await ctx.blockchain.get_gas_price(),
                "nonce": await ctx.blockchain.get_transaction_count(
                    ctx.settings.wallet_private_key[:42]
                ),
                "chainId": await ctx.blockchain.get_chain_id(),
            })

            from eth_account import Account

            signed = Account.sign_transaction(tx_data, ctx.settings.wallet_private_key)
            tx_hash = await ctx.blockchain.send_raw_transaction(signed.raw_transaction)

            return ToolResult.success({
                "status": "SENT",
                "tx_hash": tx_hash,
                "token": validated.token_address,
                "to": validated.to,
                "amount": validated.amount,
            })
        except Exception as e:
            return ToolResult.failure(f"ERC-20 transfer failed: {e}")
