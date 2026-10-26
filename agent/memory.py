"""Conversation memory with token-bounded history.

Keeps the most recent messages within a token budget, always preserving
the system prompt. When the budget is exceeded, oldest user/assistant
messages are dropped.
"""

from __future__ import annotations

import logging
from typing import Any

from agent.llm.base import TiktokenCounter, TokenCounter

logger = logging.getLogger(__name__)


class ConversationMemory:
    """Token-bounded conversation history.

    Args:
        max_tokens: Maximum token budget (after buffer).
        counter: Token counter implementation.
    """

    def __init__(
        self,
        max_tokens: int = 6400,
        counter: TokenCounter | None = None,
    ) -> None:
        self._max_tokens = max_tokens
        self._counter = counter or TiktokenCounter()
        self._messages: list[dict[str, Any]] = []
        self._system_prompt: dict[str, Any] | None = None

    def set_system_prompt(self, content: str) -> None:
        """Set (or replace) the system prompt. Always preserved."""
        self._system_prompt = {"role": "system", "content": content}

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to history."""
        self._messages.append(message)
        self._trim()

    def add_user(self, content: str) -> None:
        self.add_message({"role": "user", "content": content})

    def add_assistant(self, content: str | None = None, tool_calls: list | None = None) -> None:
        msg: dict[str, Any] = {"role": "assistant"}
        if content:
            msg["content"] = content
        if tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in tool_calls
            ]
        self.add_message(msg)

    def add_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.add_message({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": content,
        })

    def get_messages(self) -> list[dict[str, Any]]:
        """Return current message list including system prompt."""
        msgs: list[dict[str, Any]] = []
        if self._system_prompt:
            msgs.append(self._system_prompt)
        msgs.extend(self._messages)
        return msgs

    def update_usage(self, usage: dict[str, int]) -> None:
        """Accept actual token usage from provider (for future budget tracking)."""
        # Currently informational; could be used for more precise budgeting
        logger.debug("Token usage: %s", usage)

    def clear(self) -> None:
        """Clear conversation history (keeps system prompt)."""
        self._messages.clear()

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def _trim(self) -> None:
        """Remove oldest non-system messages to stay within token budget."""
        while self._current_tokens() > self._max_tokens and len(self._messages) > 1:
            removed = self._messages.pop(0)
            logger.debug("Trimmed message to stay within token budget: %s", removed.get("role"))

    def _current_tokens(self) -> int:
        return self._counter.count_messages(self.get_messages())
