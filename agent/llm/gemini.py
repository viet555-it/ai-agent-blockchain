"""Gemini (Google) LLM adapter via google-genai SDK."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from agent.llm.base import LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class GeminiProvider:
    """LLM adapter for Google Gemini models.

    Uses the ``google-genai`` SDK. Default model: ``gemini-2.0-flash``.
    """

    def __init__(self, api_key: str, model: str = "") -> None:
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model = model or "gemini-2.0-flash"
        logger.info("GeminiProvider initialized with model=%s", self._model)

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        from google.genai import types

        # Convert messages to Gemini format
        contents = _convert_messages(messages)

        # Build config
        config_kwargs: dict[str, Any] = {}
        if tools:
            config_kwargs["tools"] = [
                types.Tool(function_declarations=[
                    types.FunctionDeclaration(**t) for t in tools
                ])
            ]

        config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=config,
        )

        # Parse response
        tool_calls: list[ToolCall] = []
        content_parts: list[str] = []

        if response.candidates:
            for part in response.candidates[0].content.parts:
                if part.function_call:
                    fc = part.function_call
                    tool_calls.append(ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    ))
                elif part.text:
                    content_parts.append(part.text)

        usage = {}
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }

        return LLMResponse(
            content="\n".join(content_parts) if content_parts else None,
            tool_calls=tool_calls,
            usage=usage,
        )


def _convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-style messages to Gemini content format."""
    contents: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        if role == "system":
            # Gemini handles system instructions differently;
            # prepend as user context
            contents.append({"role": "user", "parts": [{"text": msg["content"]}]})
            contents.append({"role": "model", "parts": [{"text": "Understood."}]})
        elif role == "assistant":
            parts = []
            if msg.get("content"):
                parts.append({"text": msg["content"]})
            # Handle tool calls in assistant messages
            for tc in msg.get("tool_calls", []):
                parts.append({
                    "function_call": {
                        "name": tc["name"],
                        "args": tc.get("arguments", {}),
                    }
                })
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            contents.append({
                "role": "user",
                "parts": [{"function_response": {
                    "name": msg.get("name", ""),
                    "response": {"result": msg.get("content", "")},
                }}],
            })
        else:
            contents.append({"role": "user", "parts": [{"text": msg.get("content", "")}]})
    return contents
