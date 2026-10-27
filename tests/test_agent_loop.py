"""Tests for the ReAct agent loop with FakeLLMProvider."""

from __future__ import annotations

import pytest

from agent.core import AgentLoop
from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider
from agent.memory import ConversationMemory
from config.settings import LLMProviderName, Settings
from services.blockchain import MockBlockchainData, MockBlockchainService
from tools.registry import _REGISTRY, ToolRegistry

# ── Helpers ───────────────────────────────────────────────────────────

TEST_ADDR = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"


def _make_settings(**overrides) -> Settings:
    defaults = {
        "llm_provider": LLMProviderName.FAKE,
        "dry_run": True,
        "max_steps": 5,
        "max_context_tokens": 8000,
        "token_budget_buffer": 0.2,
        "sepolia_rpc_url": "https://rpc.sepolia.org",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_mock_blockchain():
    data = MockBlockchainData(
        balances={TEST_ADDR.lower(): 5 * 10**18},
        gas_price=20 * 10**9,
        chain_id=11155111,
    )
    return MockBlockchainService(data)


@pytest.fixture(autouse=True)
def _ensure_tools():
    """Manually register tools since conftest clears registry before each test."""
    from tools.read.get_gas_price import GetGasPrice
    from tools.read.get_native_balance import GetNativeBalance

    for cls in [GetNativeBalance, GetGasPrice]:
        instance = cls()
        _REGISTRY[instance.name] = instance


# ── Agent Loop Tests ──────────────────────────────────────────────────


class TestAgentLoopDirect:
    """Test the agent loop responds to direct text without tool calls."""

    @pytest.mark.asyncio
    async def test_direct_answer(self):
        """LLM gives a direct answer without calling tools."""
        llm = FakeLLMProvider(responses=[
            LLMResponse(content="Hello! I'm your blockchain assistant."),
        ])
        settings = _make_settings()
        blockchain = _make_mock_blockchain()
        registry = ToolRegistry(enabled_override=["get_native_balance", "get_gas_price"])

        loop = AgentLoop(
            llm=llm, registry=registry,
            blockchain=blockchain, settings=settings,
        )
        events = await loop.run("Hi")

        assert len(events) == 1
        assert events[0]["type"] == "final"
        assert "blockchain" in events[0]["data"]["content"].lower()

    @pytest.mark.asyncio
    async def test_single_tool_call(self):
        """LLM calls one tool then gives final answer."""
        llm = FakeLLMProvider(responses=[
            LLMResponse(tool_calls=[
                ToolCall(id="call_1", name="get_native_balance",
                         arguments={"address": TEST_ADDR}),
            ]),
            LLMResponse(content="The balance is 5 ETH."),
        ])
        settings = _make_settings()
        blockchain = _make_mock_blockchain()
        registry = ToolRegistry(enabled_override=["get_native_balance", "get_gas_price"])

        loop = AgentLoop(
            llm=llm, registry=registry,
            blockchain=blockchain, settings=settings,
        )
        events = await loop.run(f"What is the balance of {TEST_ADDR}?")

        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "final" in types

        # Verify tool result
        tool_result = next(e for e in events if e["type"] == "tool_result")
        assert tool_result["data"]["result"]["ok"] is True
        assert "5.000000" in str(tool_result["data"]["result"]["data"])

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        """LLM requests a tool that doesn't exist."""
        llm = FakeLLMProvider(responses=[
            LLMResponse(tool_calls=[
                ToolCall(id="call_1", name="nonexistent_tool",
                         arguments={}),
            ]),
            LLMResponse(content="Sorry, I couldn't find that tool."),
        ])
        settings = _make_settings()
        blockchain = _make_mock_blockchain()
        registry = ToolRegistry(enabled_override=["get_native_balance"])

        loop = AgentLoop(
            llm=llm, registry=registry,
            blockchain=blockchain, settings=settings,
        )
        events = await loop.run("Do something impossible")

        # Should have tool_call + error result + final
        tool_result = next(e for e in events if e["type"] == "tool_result")
        assert tool_result["data"]["result"]["ok"] is False
        assert "not found" in tool_result["data"]["result"]["error"]

    @pytest.mark.asyncio
    async def test_max_steps_exceeded(self):
        """Agent hits max steps and stops."""
        # LLM always requests tools, never gives final answer
        responses = [
            LLMResponse(tool_calls=[
                ToolCall(id=f"call_{i}", name="get_gas_price", arguments={}),
            ])
            for i in range(10)
        ]
        llm = FakeLLMProvider(responses=responses)
        settings = _make_settings(max_steps=3)
        blockchain = _make_mock_blockchain()
        registry = ToolRegistry(enabled_override=["get_native_balance", "get_gas_price"])

        loop = AgentLoop(
            llm=llm, registry=registry,
            blockchain=blockchain, settings=settings,
        )
        events = await loop.run("Loop forever")

        # Last event should be max-steps error
        assert events[-1]["type"] == "error"
        assert "max steps" in events[-1]["data"]["error"].lower()


class TestConversationMemory:
    def test_system_prompt_preserved(self):
        mem = ConversationMemory(max_tokens=1000)
        mem.set_system_prompt("You are an assistant.")
        mem.add_user("Hello")
        msgs = mem.get_messages()
        assert msgs[0]["role"] == "system"
        assert msgs[1]["role"] == "user"

    def test_message_count(self):
        mem = ConversationMemory(max_tokens=10000)
        mem.add_user("a")
        mem.add_assistant(content="b")
        assert mem.message_count == 2

    def test_clear(self):
        mem = ConversationMemory(max_tokens=10000)
        mem.set_system_prompt("sys")
        mem.add_user("a")
        mem.clear()
        assert mem.message_count == 0
        # System prompt still there
        msgs = mem.get_messages()
        assert len(msgs) == 1
        assert msgs[0]["role"] == "system"


class TestFakeLLMProvider:
    @pytest.mark.asyncio
    async def test_scripted_responses(self):
        llm = FakeLLMProvider(responses=[
            LLMResponse(content="Response 1"),
            LLMResponse(content="Response 2"),
        ])
        r1 = await llm.chat([{"role": "user", "content": "hi"}])
        r2 = await llm.chat([{"role": "user", "content": "bye"}])
        assert r1.content == "Response 1"
        assert r2.content == "Response 2"
        assert llm.total_calls == 2

    @pytest.mark.asyncio
    async def test_exhausted_responses(self):
        llm = FakeLLMProvider(responses=[])
        r = await llm.chat([{"role": "user", "content": "hi"}])
        assert "no more" in r.content.lower()
