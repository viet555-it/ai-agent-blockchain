"""Extra coverage tests for tools/registry.py schema exports and tool edge cases."""

from __future__ import annotations

import pytest

from tools.base import ToolContext
from tools.registry import _REGISTRY, ToolRegistry

# ── Fixtures ──────────────────────────────────────────────────────────

TEST_ADDR = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD68"


class FakeSettings:
    etherscan_api_key = ""
    sepolia_rpc_url = "https://rpc.sepolia.org"
    wallet_private_key = "0x" + "ab" * 32
    dry_run = True
    max_steps = 10
    max_context_tokens = 8000
    token_budget_buffer = 0.2
    effective_token_budget = 6400


@pytest.fixture(autouse=True)
def _register_all_tools():
    """Register all tools for these tests."""
    from tools.read.estimate_gas import EstimateGas
    from tools.read.get_block import GetBlock
    from tools.read.get_erc20_balance import GetERC20Balance
    from tools.read.get_gas_price import GetGasPrice
    from tools.read.get_native_balance import GetNativeBalance
    from tools.read.get_token_info import GetTokenInfo
    from tools.read.get_transaction import GetTransaction
    from tools.read.get_transaction_history import GetTransactionHistory
    from tools.read.read_contract import ReadContract
    from tools.write.call_contract import CallContract
    from tools.write.transfer_erc20 import TransferERC20
    from tools.write.transfer_eth import TransferEth

    all_tools = [
        GetNativeBalance, GetERC20Balance, GetTokenInfo, GetTransaction,
        GetTransactionHistory, GetBlock, GetGasPrice, EstimateGas, ReadContract,
        TransferEth, TransferERC20, CallContract,
    ]
    for cls in all_tools:
        inst = cls()
        _REGISTRY[inst.name] = inst


# ── Registry schema export tests ─────────────────────────────────────


class TestRegistryExports:
    def test_openai_tools_format(self):
        reg = ToolRegistry(enabled_override=list(_REGISTRY.keys()))
        tools = reg.to_openai_tools()
        assert len(tools) == len(_REGISTRY)
        for t in tools:
            assert "type" in t
            assert t["type"] == "function"
            assert "function" in t
            assert "name" in t["function"]
            assert "parameters" in t["function"]

    def test_anthropic_tools_format(self):
        reg = ToolRegistry(enabled_override=list(_REGISTRY.keys()))
        tools = reg.to_anthropic_tools()
        assert len(tools) == len(_REGISTRY)
        for t in tools:
            assert "name" in t
            assert "input_schema" in t

    def test_gemini_tools_format(self):
        reg = ToolRegistry(enabled_override=list(_REGISTRY.keys()))
        tools = reg.to_gemini_tools()
        assert len(tools) == len(_REGISTRY)
        for t in tools:
            assert "name" in t
            assert "parameters" in t

    def test_get_unknown_returns_none(self):
        reg = ToolRegistry(enabled_override=["get_gas_price"])
        assert reg.get("nonexistent_tool") is None

    def test_list_names(self):
        reg = ToolRegistry(enabled_override=["get_gas_price", "get_block"])
        names = reg.list_names()
        assert "get_gas_price" in names
        assert "get_block" in names


# ── read_contract edge cases ─────────────────────────────────────────


class TestReadContractEdgeCases:
    @pytest.fixture()
    def ctx(self):
        from services.blockchain import MockBlockchainData, MockBlockchainService
        data = MockBlockchainData(
            contract_results={
                "0xtoken:totalSupply": 10**18,
                "0xtoken:balanceof": 5000,
            },
        )
        return ToolContext(blockchain=MockBlockchainService(data), settings=FakeSettings())

    @pytest.mark.asyncio
    async def test_read_contract_success(self, ctx):
        tool = _REGISTRY.get("read_contract")
        args = tool.validate_args({
            "contract_address": "0xToken",
            "abi_filename": "erc20.json",
            "function_name": "totalSupply",
            "args": [],
        })
        result = await tool.run(args, ctx)
        assert result.ok
        assert str(result.data["result"]) == str(10**18)

    @pytest.mark.asyncio
    async def test_read_contract_missing_abi(self, ctx):
        tool = _REGISTRY.get("read_contract")
        args = tool.validate_args({
            "contract_address": "0xToken",
            "abi_filename": "nonexistent.json",
            "function_name": "totalSupply",
        })
        result = await tool.run(args, ctx)
        assert not result.ok
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_read_contract_function_not_in_abi(self, ctx):
        tool = _REGISTRY.get("read_contract")
        args = tool.validate_args({
            "contract_address": "0xToken",
            "abi_filename": "erc20.json",
            "function_name": "nonexistent_function",
        })
        result = await tool.run(args, ctx)
        assert not result.ok

    @pytest.mark.asyncio
    async def test_read_contract_non_view_blocked(self, ctx):
        """Calling a non-view function via read_contract should fail."""
        tool = _REGISTRY.get("read_contract")
        args = tool.validate_args({
            "contract_address": "0xToken",
            "abi_filename": "SampleVault.json",
            "function_name": "deposit",
        })
        result = await tool.run(args, ctx)
        assert not result.ok


# ── WRITE tool validation edge cases ─────────────────────────────────


class TestWriteToolValidation:
    @pytest.fixture()
    def ctx(self):
        from services.blockchain import MockBlockchainData, MockBlockchainService
        data = MockBlockchainData(gas_price=20 * 10**9, chain_id=11155111)
        return ToolContext(blockchain=MockBlockchainService(data), settings=FakeSettings())

    @pytest.mark.asyncio
    async def test_transfer_eth_zero_value(self, ctx):
        tool = _REGISTRY.get("transfer_eth")
        args = tool.validate_args({"to": TEST_ADDR, "value_eth": "0"})
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["status"] == "DRY_RUN"

    @pytest.mark.asyncio
    async def test_call_contract_view_function_blocked(self, ctx):
        """call_contract should reject view/pure functions."""
        tool = _REGISTRY.get("call_contract")
        args = tool.validate_args({
            "contract_address": "0x0000000000000000000000000000000000000000",
            "abi_filename": "erc20.json",
            "function_name": "totalSupply",
        })
        result = await tool.run(args, ctx)
        assert not result.ok

    @pytest.mark.asyncio
    async def test_call_contract_missing_abi(self, ctx):
        tool = _REGISTRY.get("call_contract")
        args = tool.validate_args({
            "contract_address": "0x0000000000000000000000000000000000000000",
            "abi_filename": "nonexistent.json",
            "function_name": "deposit",
        })
        result = await tool.run(args, ctx)
        assert not result.ok
        assert "not found" in result.error.lower()
