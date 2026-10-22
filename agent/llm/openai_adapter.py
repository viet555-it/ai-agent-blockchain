"""OpenAI LLM adapter."""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.llm.base import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OpenAIProvider:
    """LLM adapter for OpenAI models.

    Default model: ``gpt-4o-mini``.
    """

    def __init__(self, api_key: str, model: str = "") -> None:
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model or "gpt-4o-mini"
        logger.info("OpenAIProvider initialized with model=%s", self._model)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    arguments=args,
                ))

        usage = {}
        if response.usage:
            usage = {
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }

        return LLMResponse(
            content=msg.content,
            tool_calls=tool_calls,
            usage=usage,
        )
