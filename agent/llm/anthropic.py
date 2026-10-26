"""Anthropic Claude LLM adapter."""

from __future__ import annotations

import logging
from typing import Any

from agent.llm.base import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class AnthropicProvider:
    """LLM adapter for Anthropic Claude models.

    Default model: ``claude-sonnet-4-20250514``.
    """

    def __init__(self, api_key: str, model: str = "") -> None:
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model or "claude-sonnet-4-20250514"
        logger.info("AnthropicProvider initialized with model=%s", self._model)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        # Extract system message
        system_text = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_text += msg.get("content", "") + "\n"
            elif msg["role"] == "tool":
                chat_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            elif msg["role"] == "assistant" and msg.get("tool_calls"):
                content_blocks: list[dict[str, Any]] = []
                if msg.get("content"):
                    content_blocks.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc.get("arguments", {}),
                    })
                chat_messages.append({"role": "assistant", "content": content_blocks})
            else:
                chat_messages.append({
                    "role": msg["role"],
                    "content": msg.get("content", ""),
                })

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": chat_messages,
            "max_tokens": 4096,
        }
        if system_text.strip():
            kwargs["system"] = system_text.strip()
        if tools:
            kwargs["tools"] = tools

        response = await self._client.messages.create(**kwargs)

        # Parse response
        tool_calls: list[ToolCall] = []
        content_parts: list[str] = []

        for block in response.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input if isinstance(block.input, dict) else {},
                ))

        usage = {
            "prompt_tokens": response.usage.input_tokens,
            "completion_tokens": response.usage.output_tokens,
            "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
        }

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            tool_calls=tool_calls,
            usage=usage,
        )
