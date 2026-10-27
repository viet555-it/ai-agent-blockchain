"""ReAct agent loop – Reasoning, Action, Observation.

The core loop:
1. Send conversation + tool definitions to LLM
2. LLM either responds with text (final answer) or requests tool calls
3. Validate tool args → execute tool → feed observation back
4. Repeat until LLM gives final answer or MAX_STEPS reached
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import ValidationError

from agent.llm.base import LLMProvider, ToolCall
from agent.memory import ContextBudgetExceededError, ConversationMemory
from agent.prompts import get_system_prompt
from config.settings import LLMProviderName, Settings
from tools.base import RiskLevel, ToolContext, ToolResult
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class AgentLoop:
    """ReAct agent loop with tool calling.

    Args:
        llm: LLM provider instance.
        registry: Tool registry (discovered).
        blockchain: BlockchainService implementation.
        settings: Application settings.
    """

    def __init__(
        self,
        llm: LLMProvider,
        registry: ToolRegistry,
        blockchain: Any,
        settings: Settings,
        memory: ConversationMemory | None = None,
        retrieval_context: str = "",
        system_prompt: str | None = None,
        request_context: dict[str, Any] | None = None,
    ) -> None:
        self.llm = llm
        self.registry = registry
        self.ctx = ToolContext(blockchain=blockchain, settings=settings,
                               request_context=dict(request_context or {}))
        self.settings = settings
        self.memory = memory or ConversationMemory(
            max_tokens=settings.effective_token_budget
        )
        self.memory.set_system_prompt((system_prompt or get_system_prompt()) + retrieval_context)
        self._provider_name = settings.llm_provider

    async def run(self, user_message: str) -> list[dict[str, Any]]:
        """Run the agent loop for a single user message.

        Returns a list of events (dicts) with types:
        ``thought``, ``tool_call``, ``tool_result``, ``final``, ``error``.
        """
        events: list[dict[str, Any]] = []
        self.memory.add_user(user_message)

        for step in range(1, self.settings.max_steps + 1):
            logger.info("Agent step %d/%d", step, self.settings.max_steps)

            # Get tool definitions in provider-native format
            tools_defs = self._get_tool_definitions()

            # Call LLM
            t0 = time.time()
            try:
                self.memory.ensure_within_budget()
                response = await self.llm.chat(
                    messages=self.memory.get_messages(),
                    tools=tools_defs if tools_defs else None,
                )
            except Exception as e:
                logger.exception("LLM call failed at step %d", step)
                diagnostic = ({"http_status": None, "reason": "CONTEXT_BUDGET_EXCEEDED"}
                              if isinstance(e, ContextBudgetExceededError) else self._diagnostic())
                events.append({"type": "error", "data": {"error": f"LLM error: {e}",
                                                          "diagnostic": diagnostic}})
                break

            latency_ms = (time.time() - t0) * 1000
            logger.debug("LLM responded in %.0fms", latency_ms)

            # Update usage if provider returned it
            if response.usage:
                self.memory.update_usage(response.usage)

            # Case 1: LLM requests tool calls
            if response.tool_calls:
                # Record assistant message with tool calls
                self.memory.add_assistant(
                    content=response.content, tool_calls=response.tool_calls,
                    provider_metadata=response.provider_metadata,
                )

                if response.content:
                    events.append({"type": "thought", "data": {"content": response.content}})

                # Execute each tool call
                for tc in response.tool_calls:
                    tc_event, tc_result = await self._execute_tool_call(tc)
                    events.append(tc_event)
                    events.append(tc_result)

                # Integrated proposal results are already rendered by the backend.
                # A second LLM request cannot authorize or improve that decision.
                context = self.ctx.request_context
                if context.get("stop_after_proposal") and context.get("proposal_results"):
                    final = "Proposal evaluated; no transaction has been sent."
                    self.memory.add_assistant(content=final)
                    events.append({"type": "final", "data": {"content": final}})
                    break

                continue  # Loop back for next LLM step

            # Case 2: LLM gives final text answer
            if response.content:
                self.memory.add_assistant(content=response.content, provider_metadata=response.provider_metadata)
                events.append({"type": "final", "data": {"content": response.content}})
                break

            # Case 3: Empty response
            events.append({
                "type": "error",
                "data": {"error": "LLM returned empty response", "diagnostic": self._diagnostic()},
            })
            break
        else:
            # Max steps reached
            events.append({
                "type": "error",
                "data": {"error": f"Agent reached max steps ({self.settings.max_steps})"},
            })

        return events

    def _diagnostic(self) -> dict[str, Any]:
        value = getattr(self.llm, "last_error", None)
        if not isinstance(value, dict):
            return {}
        # Providers own these fields; never copy arbitrary exception/payload text.
        result = {"http_status": value.get("http_status") if type(value.get("http_status")) is int else None}
        reasons = {"INVALID_TOOL_HISTORY", "THOUGHT_SIGNATURE", "INVALID_TOOL_SCHEMA",
                   "CONTEXT_LIMIT", "EMPTY_RESPONSE", "MAX_TOKENS", "SAFETY",
                   "MALFORMED_FUNCTION_CALL", "PROVIDER_HTTP_ERROR"}
        if value.get("reason") in reasons:
            result["reason"] = value["reason"]
        return result

    async def _execute_tool_call(
        self, tc: ToolCall
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Execute a single tool call and return (tool_call_event, tool_result_event)."""
        call_event = {
            "type": "tool_call",
            "data": {"id": tc.id, "name": tc.name, "arguments": tc.arguments},
        }

        tool = self.registry.get(tc.name)
        if tool is None:
            error_msg = f"Tool '{tc.name}' not found or disabled."
            self.memory.add_tool_result(tc.id, tc.name, json.dumps({"error": error_msg}))
            return call_event, {
                "type": "tool_result",
                "data": {"id": tc.id, "name": tc.name, "result": {"ok": False, "error": error_msg}},
            }

        # WRITE tools: log elevated risk, then let tool run its own policy checks
        if tool.risk_level == RiskLevel.WRITE:
            logger.warning(
                "WRITE tool '%s' requested – policy checks delegated to tool", tc.name
            )

        # Validate arguments
        try:
            validated = tool.validate_args(tc.arguments)
        except ValidationError as e:
            error_msg = f"Invalid arguments for '{tc.name}': {e}"
            self.memory.add_tool_result(tc.id, tc.name, json.dumps({"error": error_msg}))
            return call_event, {
                "type": "tool_result",
                "data": {"id": tc.id, "name": tc.name, "result": {"ok": False, "error": error_msg}},
            }

        # Execute tool
        t0 = time.time()
        try:
            result = await tool.run(validated, self.ctx)
        except Exception as e:
            logger.exception("Tool '%s' raised unexpected exception", tc.name)
            result = ToolResult.failure(f"Tool execution error: {e}")

        duration_ms = (time.time() - t0) * 1000
        logger.info("Tool '%s' completed in %.0fms (ok=%s)", tc.name, duration_ms, result.ok)

        # Feed result back to memory
        result_json = result.model_dump_json()
        self.memory.add_tool_result(tc.id, tc.name, result_json)

        return call_event, {
            "type": "tool_result",
            "data": {
                "id": tc.id,
                "name": tc.name,
                "result": result.model_dump(),
                "duration_ms": round(duration_ms, 1),
            },
        }

    def _get_tool_definitions(self) -> list[dict[str, Any]]:
        """Get tool definitions in the format expected by the current LLM provider."""
        match self._provider_name:
            case LLMProviderName.ANTHROPIC:
                return self.registry.to_anthropic_tools()
            case LLMProviderName.GEMINI:
                return self.registry.to_gemini_tools()
            case _:
                # OpenAI format is the default (also used by Fake)
                return self.registry.to_openai_tools()
