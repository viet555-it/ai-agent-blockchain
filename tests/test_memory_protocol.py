"""Oversized observations must not turn valid tool history into orphan results."""
import pytest

from agent.llm.base import TiktokenCounter, ToolCall
from agent.llm.gemini import _convert_messages
from agent.memory import ContextBudgetExceededError, ConversationMemory


def test_large_active_turn_keeps_user_and_signed_calls_but_refuses_next_request():
    memory = ConversationMemory(max_tokens=150)
    memory.set_system_prompt("READ only")
    memory.add_user("Look up the deployment transaction")
    metadata = {"provider": "gemini", "parts": [{"function_call": {
        "id": "one", "name": "get_transaction", "args": {}}, "thought_signature": b"opaque"}]}
    memory.add_assistant(tool_calls=[ToolCall("one", "get_transaction", {})], provider_metadata=metadata)
    memory.add_tool_result("one", "get_transaction", '{"input":"' + "1234567890abcdef" * 2000 + '"}')
    assert [m["role"] for m in memory.get_messages()] == ["system", "user", "assistant", "tool"]
    assert _convert_messages(memory.get_messages())[1]["parts"][0]["thought_signature"] == b"opaque"
    with pytest.raises(ContextBudgetExceededError):
        memory.ensure_within_budget()


def test_pruning_evicts_entire_old_turn_not_half_a_tool_exchange():
    memory = ConversationMemory(max_tokens=200)
    memory.add_user("Old question " * 10)
    memory.add_assistant(tool_calls=[ToolCall("one", "read", {})])
    memory.add_tool_result("one", "read", "Old observation " * 100)
    memory.add_user("New question")
    assert memory.get_messages() == [{"role": "user", "content": "New question"}]
    memory.ensure_within_budget()


def test_tool_arguments_are_counted_in_context_budget():
    counter = TiktokenCounter()
    plain = counter.count_messages([{"role": "assistant"}])
    with_args = counter.count_messages([{"role": "assistant", "tool_calls": [
        {"id": "one", "name": "read", "arguments": {"data": "long " * 300}}]}])
    assert with_args > plain + 250


@pytest.mark.asyncio
async def test_oversized_tool_observation_never_triggers_a_second_provider_call():
    from pydantic import BaseModel

    from agent.core import AgentLoop
    from agent.llm.base import LLMResponse
    from agent.llm.fake import FakeLLMProvider
    from config.settings import Settings
    from tools.base import BaseTool, RiskLevel, ToolResult
    from tools.registry import ToolRegistry

    class Args(BaseModel):
        pass

    class HugeRead(BaseTool):
        name = "huge_read"
        description = "Read a large result"
        risk_level = RiskLevel.READ
        args_schema = Args

        async def run(self, validated, ctx):
            return ToolResult.success({"input": "1234567890abcdef" * 2000})

    registry = ToolRegistry(enabled_override=["huge_read"])
    from unittest.mock import patch
    llm = FakeLLMProvider([LLMResponse(tool_calls=[ToolCall("one", "huge_read", {})])])
    loop = AgentLoop(llm, registry, None, Settings(_env_file=None, llm_provider="fake"),
                     memory=ConversationMemory(max_tokens=200), system_prompt="READ only")
    with (patch.object(registry, "get", return_value=HugeRead()),
          patch.object(registry, "all_tools", return_value={"huge_read": HugeRead()})):
        events = await loop.run("Read the transaction")
    assert llm.total_calls == 1
    assert events[-1]["data"]["diagnostic"]["reason"] == "CONTEXT_BUDGET_EXCEEDED"
    _convert_messages(loop.memory.get_messages())
