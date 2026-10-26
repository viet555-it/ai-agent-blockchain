"""Tests for eval/run_eval.py module logic and additional coverage gaps."""

from __future__ import annotations

import pytest

from agent.llm.base import LLMResponse, TiktokenCounter
from eval.run_eval import EvalResult, FakeScriptedLLM, generate_report

# ── EvalResult tests ──────────────────────────────────────────────────


class TestEvalResult:
    def test_tool_correct(self):
        r = EvalResult("prompt", "get_gas_price", "get_gas_price", {}, {}, "read")
        assert r.tool_correct
        assert r.fully_correct

    def test_tool_wrong(self):
        r = EvalResult("prompt", "get_gas_price", "get_block", {}, {}, "read")
        assert not r.tool_correct
        assert not r.fully_correct

    def test_no_tool_expected_and_none_called(self):
        r = EvalResult("hello", None, None, {}, {}, "no_tool")
        assert r.tool_correct
        assert r.fully_correct

    def test_args_correct(self):
        r = EvalResult("p", "t", "t", {"address": "0xABC"}, {"address": "0xabc", "extra": "x"}, "c")
        assert r.args_correct  # case-insensitive, extra args ignored

    def test_args_missing(self):
        r = EvalResult("p", "t", "t", {"address": "0xABC"}, {}, "c")
        assert not r.args_correct

    def test_to_dict(self):
        r = EvalResult("prompt", "tool", "tool", {}, {}, "cat")
        d = r.to_dict()
        assert d["tool_ok"] == "✅"
        assert d["category"] == "cat"


class TestGenerateReport:
    def test_report_contains_summary(self):
        results = [
            EvalResult("p1", "t1", "t1", {}, {}, "cat1"),
            EvalResult("p2", None, None, {}, {}, "cat2"),
            EvalResult("p3", "t3", "t4", {}, {}, "cat1"),  # wrong
        ]
        report = generate_report(results)
        assert "Tool Selection" in report
        assert "Category Breakdown" in report
        assert "Failures" in report
        assert "2/3" in report  # 2 correct out of 3


class TestFakeScriptedLLM:
    @pytest.mark.asyncio
    async def test_returns_tool_for_matching_prompt(self):
        dataset = [{"prompt": "What is gas?", "expected_tool": "get_gas_price", "expected_args": {}}]
        llm = FakeScriptedLLM(dataset)
        response = await llm.chat([{"role": "user", "content": "What is gas?"}])
        assert len(response.tool_calls) == 1
        assert response.tool_calls[0].name == "get_gas_price"

    @pytest.mark.asyncio
    async def test_returns_text_for_no_tool(self):
        dataset = [{"prompt": "Hello", "expected_tool": None}]
        llm = FakeScriptedLLM(dataset)
        response = await llm.chat([{"role": "user", "content": "Hello"}])
        assert response.content
        assert not response.tool_calls

    @pytest.mark.asyncio
    async def test_returns_final_after_tool_result(self):
        dataset = [{"prompt": "p", "expected_tool": "t"}]
        llm = FakeScriptedLLM(dataset)
        msgs = [
            {"role": "user", "content": "p"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "name": "t"}]},
            {"role": "tool", "tool_call_id": "1", "name": "t", "content": "result"},
        ]
        response = await llm.chat(msgs)
        assert response.content  # should give final answer
        assert not response.tool_calls


# ── TiktokenCounter tests ────────────────────────────────────────────


class TestTiktokenCounter:
    def test_count(self):
        counter = TiktokenCounter()
        count = counter.count("Hello, world!")
        assert count > 0

    def test_count_messages(self):
        counter = TiktokenCounter()
        msgs = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello!"},
        ]
        count = counter.count_messages(msgs)
        assert count > 0

    def test_empty_text(self):
        counter = TiktokenCounter()
        assert counter.count("") == 0


# ── Additional agent/core coverage ───────────────────────────────────


class TestAgentCoreLLMError:
    @pytest.mark.asyncio
    async def test_llm_error_produces_error_event(self):
        from agent.core import AgentLoop
        from agent.llm.fake import FakeLLMProvider
        from config.settings import LLMProviderName, Settings
        from services.blockchain import MockBlockchainData, MockBlockchainService
        from tools.registry import ToolRegistry

        class ErrorLLM(FakeLLMProvider):
            async def chat(self, messages, tools=None):
                raise RuntimeError("API down")

        llm = ErrorLLM()
        settings = Settings(llm_provider=LLMProviderName.FAKE, max_steps=3)
        blockchain = MockBlockchainService(MockBlockchainData())
        registry = ToolRegistry(enabled_override=[])

        loop = AgentLoop(llm=llm, registry=registry, blockchain=blockchain, settings=settings)
        events = await loop.run("Hello")

        assert events[-1]["type"] == "error"
        assert "LLM error" in events[-1]["data"]["error"]

    @pytest.mark.asyncio
    async def test_empty_llm_response(self):
        from agent.core import AgentLoop
        from agent.llm.fake import FakeLLMProvider
        from config.settings import LLMProviderName, Settings
        from services.blockchain import MockBlockchainData, MockBlockchainService
        from tools.registry import ToolRegistry

        llm = FakeLLMProvider(responses=[
            LLMResponse(content=None, tool_calls=[]),
        ])
        settings = Settings(llm_provider=LLMProviderName.FAKE, max_steps=3)
        blockchain = MockBlockchainService(MockBlockchainData())
        registry = ToolRegistry(enabled_override=[])

        loop = AgentLoop(llm=llm, registry=registry, blockchain=blockchain, settings=settings)
        events = await loop.run("Hello")

        assert events[-1]["type"] == "error"
        assert "empty" in events[-1]["data"]["error"].lower()


# ── Additional settings coverage ─────────────────────────────────────


class TestSettingsExtra:
    def test_repr_masks_keys(self):
        from config.settings import Settings
        s = Settings(gemini_api_key="secret123", wallet_private_key="0xsecret")
        r = repr(s)
        assert "secret123" not in r
        assert "***" in r

    def test_load_abi_not_found(self):
        from config.settings import load_abi
        with pytest.raises(FileNotFoundError):
            load_abi("nonexistent_abi.json")

    def test_load_yaml_missing_file(self):
        from config.settings import load_yaml_config
        result = load_yaml_config("nonexistent.yaml")
        assert result == {}

    def test_effective_token_budget(self):
        from config.settings import Settings
        s = Settings(max_context_tokens=10000, token_budget_buffer=0.2)
        assert s.effective_token_budget == 8000

    def test_get_settings_singleton(self):
        from config.settings import get_settings, reset_settings
        reset_settings()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        reset_settings()


# ── Registry schema export coverage ──────────────────────────────────


class TestRegistryAutoDiscover:
    def test_auto_discover_loads_tools(self):
        from tools.read.get_gas_price import GetGasPrice
        from tools.registry import _REGISTRY, ToolRegistry
        # Manually register since conftest clears registry
        _REGISTRY["get_gas_price"] = GetGasPrice()
        reg = ToolRegistry(enabled_override=["get_gas_price"])
        names = reg.list_names()
        assert len(names) > 0
        assert "get_gas_price" in names


# ── Memory trimming coverage ─────────────────────────────────────────


class TestMemoryTrimming:
    def test_trim_removes_old_messages(self):
        from agent.memory import ConversationMemory
        # Very small budget to force trimming
        mem = ConversationMemory(max_tokens=50)
        mem.set_system_prompt("sys")
        for i in range(20):
            mem.add_user(f"message {i} " * 10)
        # Should have trimmed to stay within budget
        assert mem.message_count < 20
