"""Fake LLM provider for deterministic testing without API calls.

``FakeLLMProvider`` takes a script of pre-defined responses and replays them
in order. Useful for testing the agent loop without burning API credits.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.llm.base import LLMResponse

logger = logging.getLogger(__name__)


class FakeLLMProvider:
    """Scripted LLM provider for testing.

    Usage::

        provider = FakeLLMProvider(responses=[
            LLMResponse(tool_calls=[ToolCall(id="1", name="get_native_balance",
                                              arguments={"address": "0xABC"})]),
            LLMResponse(content="The balance is 5 ETH."),
        ])
    """

    def __init__(self, responses: list[LLMResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_count = 0
        self.call_history: list[dict[str, Any]] = []

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.call_history.append({
            "messages": messages,
            "tools": tools,
            "call_index": self._call_count,
        })

        if self._call_count >= len(self._responses):
            logger.warning(
                "FakeLLMProvider: no more scripted responses (call #%d), "
                "returning empty final response.",
                self._call_count,
            )
            return LLMResponse(content="[FakeLLM: no more scripted responses]")

        response = self._responses[self._call_count]
        self._call_count += 1
        return response

    @property
    def total_calls(self) -> int:
        return self._call_count

    def reset(self) -> None:
        """Reset call counter for re-use."""
        self._call_count = 0
        self.call_history.clear()
