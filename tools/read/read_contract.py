"""Tool: read_contract – Call a view/pure function on a smart contract."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool


class ReadContractInput(BaseModel):
    contract_address: str = Field(description="Address of the smart contract")
    abi_filename: str = Field(
        default="erc20.json",
        description="ABI filename in the abis/ directory (e.g. 'erc20.json', 'SampleVault.json')",
    )
    function_name: str = Field(description="Name of the view/pure function to call")
    args: list = Field(default_factory=list, description="Arguments to pass to the function")


@register_tool
class ReadContract(BaseTool):
    name = "read_contract"
    description = (
        "Call a read-only (view/pure) function on a smart contract. "
        "Requires the ABI file to be present in the abis/ directory. "
        "Cannot modify state – use call_contract for state-changing functions."
    )
    risk_level = RiskLevel.READ
    args_schema = ReadContractInput

    async def run(self, validated: ReadContractInput, ctx: ToolContext) -> ToolResult:
        try:
            from config.settings import load_abi

            abi = load_abi(validated.abi_filename)

            # Verify function exists and is view/pure
            fn_abi = None
            for item in abi:
                if (
                    item.get("type") == "function"
                    and item.get("name") == validated.function_name
                ):
                    fn_abi = item
                    break

            if fn_abi is None:
                return ToolResult.failure(
                    f"Function '{validated.function_name}' not found in ABI '{validated.abi_filename}'. "
                    f"Available functions: {[i['name'] for i in abi if i.get('type') == 'function']}"
                )

            mutability = fn_abi.get("stateMutability", "")
            if mutability not in ("view", "pure"):
                return ToolResult.failure(
                    f"Function '{validated.function_name}' is '{mutability}', not view/pure. "
                    "Use call_contract for state-changing functions."
                )

            result = await ctx.blockchain.read_contract(
                validated.contract_address,
                abi,
                validated.function_name,
                validated.args,
            )

            # Serialize result for JSON compatibility
            serialized = _serialize(result)
            return ToolResult.success({
                "contract": validated.contract_address,
                "function": validated.function_name,
                "args": validated.args,
                "result": serialized,
            })
        except FileNotFoundError:
            return ToolResult.failure(
                f"ABI file '{validated.abi_filename}' not found in abis/ directory."
            )
        except Exception as e:
            return ToolResult.failure(f"Failed to read contract: {e}")


def _serialize(value: object) -> object:
    """Make contract return values JSON-serializable."""
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, int) and abs(value) > 2**53:
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)
