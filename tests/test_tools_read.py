"""Tests for READ tools – run against MockBlockchainService."""

from __future__ import annotations

import pytest

from services.blockchain import MockBlockchainData, MockBlockchainService
from tools.base import ToolContext
from tools.registry import _REGISTRY

# ── Fixtures ──────────────────────────────────────────────────────────

TEST_ADDR = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
TEST_TOKEN = "0xTestToken0000000000000000000000000000001"
TEST_TX = "0xabc123"


class FakeSettings:
    """Minimal settings stub for ToolContext."""
    etherscan_api_key = ""
    sepolia_rpc_url = "https://rpc.sepolia.org"
    dry_run = True
    max_steps = 10
    max_context_tokens = 8000
    token_budget_buffer = 0.2
    effective_token_budget = 6400


@pytest.fixture()
def mock_blockchain():
    data = MockBlockchainData(
        balances={TEST_ADDR.lower(): 5 * 10**18},
        erc20_balances={
            TEST_TOKEN.lower(): {TEST_ADDR.lower(): 1000 * 10**6},
        },
        token_info={
            TEST_TOKEN.lower(): {"name": "Test Token", "symbol": "TST", "decimals": 6, "total_supply": 10**9}
        },
        transactions={
            TEST_TX.lower(): {
                "hash": TEST_TX,
                "from": TEST_ADDR,
                "to": "0x000",
                "value": 10**18,
                "gas": 21000,
                "gasPrice": 20 * 10**9,
                "blockNumber": 100,
            }
        },
        gas_price=20 * 10**9,
        chain_id=11155111,
        blocks={
            "latest": {
                "number": 100,
                "timestamp": 1700000000,
                "transactions": ["0xtx1", "0xtx2"],
                "gasUsed": 300000,
                "gasLimit": 30000000,
            }
        },
    )
    return MockBlockchainService(data)


@pytest.fixture()
def ctx(mock_blockchain):
    return ToolContext(blockchain=mock_blockchain, settings=FakeSettings())


@pytest.fixture(autouse=True)
def _discover_tools():
    """Register READ tools into the global registry for each test.

    The conftest autouse _clean_registry clears _REGISTRY before each test,
    so import-time @register_tool won't re-fire. We manually register here.
    """
    from tools.read.estimate_gas import EstimateGas
    from tools.read.get_block import GetBlock
    from tools.read.get_erc20_balance import GetERC20Balance
    from tools.read.get_gas_price import GetGasPrice
    from tools.read.get_native_balance import GetNativeBalance
    from tools.read.get_token_info import GetTokenInfo
    from tools.read.get_transaction import GetTransaction
    from tools.read.get_transaction_history import GetTransactionHistory
    from tools.read.read_contract import ReadContract

    for cls in [GetNativeBalance, GetERC20Balance, GetTokenInfo, GetTransaction,
                GetTransactionHistory, GetBlock, GetGasPrice, EstimateGas, ReadContract]:
        instance = cls()
        _REGISTRY[instance.name] = instance


def _get_tool(name: str):
    """Get tool directly from registry, bypassing enabled filter."""
    return _REGISTRY.get(name)


# ── Tests ─────────────────────────────────────────────────────────────


class TestGetNativeBalance:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = _get_tool("get_native_balance")
        args = tool.validate_args({"address": TEST_ADDR})
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["balance_eth"] == "5.000000"

    @pytest.mark.asyncio
    async def test_unknown_address(self, ctx):
        tool = _get_tool("get_native_balance")
        args = tool.validate_args({"address": "0xUnknown"})
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["balance_eth"] == "0.000000"


class TestGetERC20Balance:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = _get_tool("get_erc20_balance")
        args = tool.validate_args({
            "token_address": TEST_TOKEN,
            "wallet_address": TEST_ADDR,
        })
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["decimals"] == 6
        assert "1000" in result.data["balance"]


class TestGetTokenInfo:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = _get_tool("get_token_info")
        args = tool.validate_args({"token_address": TEST_TOKEN})
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["symbol"] == "TST"
        assert result.data["decimals"] == 6

    @pytest.mark.asyncio
    async def test_cache(self, ctx):
        tool = _get_tool("get_token_info")
        args = tool.validate_args({"token_address": TEST_TOKEN})
        await tool.run(args, ctx)
        result2 = await tool.run(args, ctx)
        assert result2.ok
        assert result2.meta == {"source": "cache"}


class TestGetTransaction:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = _get_tool("get_transaction")
        args = tool.validate_args({"tx_hash": TEST_TX})
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["from"] == TEST_ADDR
        assert result.data["status"] == "confirmed"

    @pytest.mark.asyncio
    async def test_not_found(self, ctx):
        tool = _get_tool("get_transaction")
        args = tool.validate_args({"tx_hash": "0xNonexistent"})
        result = await tool.run(args, ctx)
        assert not result.ok


class TestGetTransactionHistory:
    @pytest.mark.asyncio
    async def test_no_etherscan_key(self, ctx):
        tool = _get_tool("get_transaction_history")
        args = tool.validate_args({"address": TEST_ADDR})
        result = await tool.run(args, ctx)
        assert not result.ok
        assert "NOT_CONFIGURED" in str(result.meta)


class TestGetBlock:
    @pytest.mark.asyncio
    async def test_latest(self, ctx):
        tool = _get_tool("get_block")
        args = tool.validate_args({"block_identifier": "latest"})
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["number"] == 100
        assert result.data["transactions_count"] == 2


class TestGetGasPrice:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = _get_tool("get_gas_price")
        args = tool.validate_args({})
        result = await tool.run(args, ctx)
        assert result.ok
        assert "gas_price_gwei" in result.data
        assert result.data["gas_price_gwei"] == "20.00"


class TestEstimateGas:
    @pytest.mark.asyncio
    async def test_success(self, ctx):
        tool = _get_tool("estimate_gas")
        args = tool.validate_args({"to": TEST_ADDR, "value_wei": "1000000"})
        result = await tool.run(args, ctx)
        assert result.ok
        assert "gas_estimate" in result.data
        assert "estimated_cost_eth" in result.data
