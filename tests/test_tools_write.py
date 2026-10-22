"""Tests for WRITE tools – run against MockBlockchainService with policy checks."""

from __future__ import annotations

import pytest

from services.blockchain import MockBlockchainData, MockBlockchainService
from tools.base import ToolContext
from tools.registry import _REGISTRY

# ── Constants ─────────────────────────────────────────────────────────

DEMO_ADDR = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD68"
UNKNOWN_ADDR = "0xDeaDbeeF00000000000000000000000000000000"
DEMO_CONTRACT = "0x0000000000000000000000000000000000000000"
TEST_TOKEN = "0xTestToken0000000000000000000000000000001"


# ── Settings stub ─────────────────────────────────────────────────────


class FakeSettings:
    etherscan_api_key = ""
    sepolia_rpc_url = "https://rpc.sepolia.org"
    wallet_private_key = "0x" + "ab" * 32  # fake key
    dry_run = True
    max_steps = 10
    max_context_tokens = 8000
    token_budget_buffer = 0.2
    effective_token_budget = 6400


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def mock_blockchain():
    data = MockBlockchainData(
        balances={DEMO_ADDR.lower(): 5 * 10**18},
        erc20_balances={
            TEST_TOKEN.lower(): {DEMO_ADDR.lower(): 1000 * 10**6},
        },
        token_info={
            TEST_TOKEN.lower(): {"name": "Test Token", "symbol": "TST", "decimals": 6, "total_supply": 10**9},
        },
        gas_price=20 * 10**9,
        chain_id=11155111,
    )
    return MockBlockchainService(data)


@pytest.fixture()
def ctx(mock_blockchain):
    return ToolContext(blockchain=mock_blockchain, settings=FakeSettings())


@pytest.fixture(autouse=True)
def _register_write_tools():
    """Register WRITE tools for each test."""
    from tools.write.call_contract import CallContract
    from tools.write.transfer_erc20 import TransferERC20
    from tools.write.transfer_eth import TransferEth

    for cls in [TransferEth, TransferERC20, CallContract]:
        instance = cls()
        _REGISTRY[instance.name] = instance


def _get_tool(name: str):
    return _REGISTRY.get(name)


# ── TransferEth tests ─────────────────────────────────────────────────


class TestTransferEth:
    @pytest.mark.asyncio
    async def test_dry_run_allowed_address(self, ctx):
        """Transfer to allowed address in dry_run mode → success preview."""
        tool = _get_tool("transfer_eth")
        args = tool.validate_args({"to": DEMO_ADDR, "value_eth": "0.01"})
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["status"] == "DRY_RUN"
        assert result.data["to"] == DEMO_ADDR

    @pytest.mark.asyncio
    async def test_policy_denies_unknown_address(self, ctx):
        """Transfer to non-allowlisted address → policy denied."""
        tool = _get_tool("transfer_eth")
        args = tool.validate_args({"to": UNKNOWN_ADDR, "value_eth": "0.01"})
        result = await tool.run(args, ctx)
        assert not result.ok
        assert "POLICY_DENIED" in str(result.meta)

    @pytest.mark.asyncio
    async def test_policy_denies_over_limit(self, ctx):
        """Transfer exceeding per-tx limit → policy denied."""
        tool = _get_tool("transfer_eth")
        args = tool.validate_args({"to": DEMO_ADDR, "value_eth": "1.0"})
        result = await tool.run(args, ctx)
        assert not result.ok
        assert "per-transaction limit" in result.error


# ── TransferERC20 tests ──────────────────────────────────────────────


class TestTransferERC20:
    @pytest.mark.asyncio
    async def test_policy_denies_unknown_recipient(self, ctx):
        """ERC-20 transfer to non-allowlisted address → denied."""
        tool = _get_tool("transfer_erc20")
        args = tool.validate_args({
            "token_address": TEST_TOKEN,
            "to": UNKNOWN_ADDR,
            "amount": "100",
        })
        result = await tool.run(args, ctx)
        assert not result.ok
        assert "POLICY_DENIED" in str(result.meta)


# ── CallContract tests ───────────────────────────────────────────────


class TestCallContract:
    @pytest.mark.asyncio
    async def test_dry_run_allowed(self, ctx):
        """Call allowed function on allowed contract in dry_run → preview."""
        tool = _get_tool("call_contract")
        args = tool.validate_args({
            "contract_address": DEMO_CONTRACT,
            "function_name": "deposit",
            "value_eth": "0.01",
        })
        result = await tool.run(args, ctx)
        assert result.ok
        assert result.data["status"] == "DRY_RUN"

    @pytest.mark.asyncio
    async def test_policy_denies_unknown_function(self, ctx):
        """Call non-allowlisted function → denied."""
        tool = _get_tool("call_contract")
        args = tool.validate_args({
            "contract_address": DEMO_CONTRACT,
            "function_name": "selfdestruct",
        })
        result = await tool.run(args, ctx)
        assert not result.ok
        assert "POLICY_DENIED" in str(result.meta)

    @pytest.mark.asyncio
    async def test_policy_denies_unknown_contract(self, ctx):
        """Call on non-allowlisted contract → denied."""
        tool = _get_tool("call_contract")
        args = tool.validate_args({
            "contract_address": UNKNOWN_ADDR,
            "function_name": "deposit",
        })
        result = await tool.run(args, ctx)
        assert not result.ok


# ── Agent integration test ───────────────────────────────────────────


class TestWriteToolInAgentLoop:
    """Verify WRITE tools execute (not blocked) in the agent loop."""

    @pytest.mark.asyncio
    async def test_write_tool_runs_through_loop(self, ctx):
        """Agent loop should execute WRITE tool (not block with M2 placeholder)."""
        from agent.core import AgentLoop
        from agent.llm.base import LLMResponse, ToolCall
        from agent.llm.fake import FakeLLMProvider
        from config.settings import LLMProviderName, Settings
        from tools.registry import ToolRegistry

        llm = FakeLLMProvider(responses=[
            LLMResponse(tool_calls=[
                ToolCall(id="call_1", name="transfer_eth",
                         arguments={"to": DEMO_ADDR, "value_eth": "0.01"}),
            ]),
            LLMResponse(content="Transfer preview shown."),
        ])
        settings = Settings(
            llm_provider=LLMProviderName.FAKE,
            dry_run=True,
            max_steps=5,
        )
        registry = ToolRegistry(enabled_override=["transfer_eth"])

        loop = AgentLoop(
            llm=llm, registry=registry,
            blockchain=ctx.blockchain, settings=settings,
        )
        events = await loop.run("Send 0.01 ETH to demo address")

        tool_result = next(e for e in events if e["type"] == "tool_result")
        # Should succeed in dry_run with DRY_RUN status (not the old M2 block)
        assert tool_result["data"]["result"]["ok"] is True
        assert tool_result["data"]["result"]["data"]["status"] == "DRY_RUN"
