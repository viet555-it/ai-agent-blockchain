"""Tool: call_contract – Call a state-changing function on a smart contract."""

from __future__ import annotations

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class CallContractInput(BaseModel):
    contract_address: str = Field(description="Smart contract address")
    abi_filename: str = Field(
        default="SampleVault.json",
        description="ABI filename in abis/ directory",
    )
    function_name: str = Field(description="Function to call (e.g. 'deposit', 'withdraw')")
    args: list = Field(default_factory=list, description="Arguments for the function")
    value_eth: str = Field(default="0", description="ETH to send with the call (for payable functions)")


@register_tool
class CallContract(BaseTool):
    name = "call_contract"
    description = (
        "Call a state-changing function on a smart contract on Sepolia. "
        "REQUIRES user confirmation. "
        "Use 'read_contract' for view/pure functions instead."
    )
    risk_level = RiskLevel.WRITE
    args_schema = CallContractInput

    async def run(self, validated: CallContractInput, ctx: ToolContext) -> ToolResult:
        try:
            value_eth = float(validated.value_eth)

            # Policy checks
            from security.policy import PolicyEngine

            policy = PolicyEngine()
            decision = policy.check_contract_call(
                validated.contract_address,
                validated.function_name,
                value_eth,
            )
            if not decision.allowed:
                return ToolResult.failure(
                    f"Policy blocked: {decision.reason}",
                    code="POLICY_DENIED",
                )

            # Load and verify ABI
            from config.settings import load_abi

            abi = load_abi(validated.abi_filename)
            fn_abi = None
            for item in abi:
                if item.get("type") == "function" and item.get("name") == validated.function_name:
                    fn_abi = item
                    break

            if fn_abi is None:
                return ToolResult.failure(
                    f"Function '{validated.function_name}' not found in ABI '{validated.abi_filename}'."
                )

            # Block view/pure functions (use read_contract instead)
            mutability = fn_abi.get("stateMutability", "")
            if mutability in ("view", "pure"):
                return ToolResult.failure(
                    f"Function '{validated.function_name}' is '{mutability}'. "
                    "Use 'read_contract' tool for read-only functions."
                )

            if ctx.settings.dry_run:
                return ToolResult.success({
                    "status": "DRY_RUN",
                    "message": "Transaction NOT sent (dry_run=true). Preview below.",
                    "contract": validated.contract_address,
                    "function": validated.function_name,
                    "args": validated.args,
                    "value_eth": validated.value_eth,
                })

            # Build and send the transaction
            value_wei = int(value_eth * 10**18)
            from web3 import Web3

            w3 = Web3()
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(validated.contract_address), abi=abi
            )
            fn = getattr(contract.functions, validated.function_name)(*validated.args)
            tx_data = fn.build_transaction({
                "value": value_wei,
                "gas": 200000,
                "gasPrice": await ctx.blockchain.get_gas_price(),
                "nonce": await ctx.blockchain.get_transaction_count(
                    ctx.settings.wallet_private_key[:42]
                ),
                "chainId": await ctx.blockchain.get_chain_id(),
            })

            from eth_account import Account

            signed = Account.sign_transaction(tx_data, ctx.settings.wallet_private_key)
            tx_hash = await ctx.blockchain.send_raw_transaction(signed.raw_transaction)

            policy.record_usage(value_eth)

            return ToolResult.success({
                "status": "SENT",
                "tx_hash": tx_hash,
                "contract": validated.contract_address,
                "function": validated.function_name,
            })
        except FileNotFoundError:
            return ToolResult.failure(
                f"ABI file '{validated.abi_filename}' not found in abis/ directory."
            )
        except Exception as e:
            return ToolResult.failure(f"Contract call failed: {e}")
