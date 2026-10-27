"""Gemini adapter with native system instructions and lossless tool-call history."""

from __future__ import annotations

import json
import uuid
from typing import Any

from agent.llm.base import LLMResponse, ToolCall

DEFAULT_MODEL = "gemini-3.5-flash-lite"


class GeminiProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "",
        *,
        max_output_tokens: int = 768,
        max_calls: int | None = None,
    ) -> None:
        from google import genai
        from google.genai import types

        if not 1 <= max_output_tokens <= 8192:
            raise ValueError("max_output_tokens must be in 1..8192")
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=30000, retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )
        self._model = model or DEFAULT_MODEL
        self._max_output_tokens = max_output_tokens
        self._max_calls = max_calls
        self.call_count = 0
        self.last_error: dict[str, Any] | None = None
        self.total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async def aclose(self) -> None:
        await self._client.aio.aclose()
        self._client.close()

    async def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMResponse:
        from google.genai import types

        if self._max_calls is not None and self.call_count >= self._max_calls:
            raise RuntimeError("Gemini request budget reached")
        config: dict[str, Any] = {"max_output_tokens": self._max_output_tokens, "temperature": 0}
        systems = [message["content"] for message in messages if message.get("role") == "system"]
        if systems:
            config["system_instruction"] = "\n\n".join(systems)
        if tools:
            config["tools"] = [
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            **{
                                **tool,
                                "parameters": _function_schema(tool["parameters"]),
                            }
                        )
                        for tool in tools
                    ]
                )
            ]
        try:
            contents = _convert_messages(messages)
        except ValueError:
            self.last_error = {"type": "ProtocolError", "http_status": None,
                               "reason": "INVALID_TOOL_HISTORY"}
            raise RuntimeError("Gemini conversation has incomplete tool history") from None
        self.call_count += 1
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(**config),
            )
        except Exception as error:
            # Provider error text may echo URLs/credentials. Keep only safe diagnostics.
            code = getattr(error, "code", None)
            self.last_error = {
                "type": type(error).__name__,
                "http_status": code if isinstance(code, int) else None,
            }
            if isinstance(code, int):
                # Classify known diagnostics without storing text, URLs or keys.
                detail = str(getattr(error, "message", "")).lower()
                reason = "PROVIDER_HTTP_ERROR"
                if "thought" in detail and "signature" in detail:
                    reason = "THOUGHT_SIGNATURE"
                elif "function response" in detail or "function_response" in detail:
                    reason = "INVALID_TOOL_HISTORY"
                elif "function_declarations" in detail or "parameters.properties" in detail:
                    reason = "INVALID_TOOL_SCHEMA"
                elif "token" in detail and ("context" in detail or "limit" in detail):
                    reason = "CONTEXT_LIMIT"
                self.last_error["reason"] = reason
            raise RuntimeError(
                f"Gemini request failed ({type(error).__name__}, HTTP {code if isinstance(code, int) else 'unknown'})"
            ) from None
        self.last_error = None
        parts = []
        if response.candidates and response.candidates[0].content:
            parts = response.candidates[0].content.parts or []
        calls = []
        text = []
        for part in parts:
            if part.function_call:
                fc = part.function_call
                calls.append(
                    ToolCall(
                        id=fc.id or f"call_{uuid.uuid4().hex[:8]}",
                        name=fc.name,
                        arguments=dict(fc.args or {}),
                    )
                )
            elif part.text and not part.thought:
                text.append(part.text)
        if not calls and not any(text):
            finish = getattr(response.candidates[0], "finish_reason", None) if response.candidates else None
            reason = getattr(finish, "value", finish)
            self.last_error = {"type": "EmptyResponse", "http_status": None,
                               "reason": reason if reason in {"MAX_TOKENS", "SAFETY", "MALFORMED_FUNCTION_CALL"} else "EMPTY_RESPONSE"}
        usage = {}
        if response.usage_metadata:
            usage = {
                "prompt_tokens": response.usage_metadata.prompt_token_count or 0,
                "completion_tokens": response.usage_metadata.candidates_token_count or 0,
                "total_tokens": response.usage_metadata.total_token_count or 0,
            }
            for name, value in usage.items():
                self.total_usage[name] += value
        return LLMResponse(
            content="\n".join(text) or None,
            tool_calls=calls,
            usage=usage,
            provider_metadata={
                "provider": "gemini",
                "parts": [part.model_dump(exclude_none=True) for part in parts],
            },
        )


def _function_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Adapt Pydantic JSON Schema to the function API's OpenAPI Schema subset.

    Validation (including extra='forbid' and defaults) remains in the tool's
    Pydantic model. Do not send JSON Schema-only annotations to `parameters`.
    """
    result = {}
    for key, value in schema.items():
        if key in {"title", "default", "additionalProperties"}:
            if key == "additionalProperties" and value is not False:
                raise ValueError("Open-ended function argument objects are unsupported")
            continue
        if key == "properties":
            result[key] = {name: _function_schema(child) for name, child in value.items()}
        elif key == "items" and isinstance(value, dict):
            result[key] = _function_schema(value)
        elif key == "anyOf":
            variants = [child for child in value if child.get("type") != "null"]
            if len(variants) == 1 and len(variants) != len(value):
                result.update(_function_schema(variants[0]))
                result["nullable"] = True
            else:
                result[key] = [_function_schema(child) for child in value]
        else:
            result[key] = value
    return result


def _convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep native Parts (including signatures) in memory across tool results."""
    native_ids = {
        part["function_call"]["id"]
        for message in messages
        for part in message.get("provider_metadata", {}).get("parts", [])
        if part.get("function_call", {}).get("id")
    }
    contents = []
    pending = {}
    for message in messages:
        role = message.get("role", "user")
        if role == "system":
            continue
        if role == "assistant":
            if pending:
                raise ValueError("Missing tool results")
            pending = {call["id"]: call["name"] for call in message.get("tool_calls", [])}
            metadata = message.get("provider_metadata", {})
            if metadata.get("provider") == "gemini" and metadata.get("parts"):
                parts = metadata["parts"]
            else:
                parts = [{"text": message["content"]}] if message.get("content") else []
                parts += [
                    {"function_call": {"name": call["name"], "args": call.get("arguments", {})}}
                    for call in message.get("tool_calls", [])
                ]
            if parts:
                contents.append({"role": "model", "parts": parts})
        elif role == "tool":
            call_id = message.get("tool_call_id")
            if call_id not in pending or pending.pop(call_id) != message.get("name"):
                raise ValueError("Orphan or mismatched tool result")
            try:
                payload = json.loads(message.get("content", ""))
            except (TypeError, ValueError):
                payload = {"result": message.get("content", "")}
            if not isinstance(payload, dict):
                payload = {"result": payload}
            response = {"name": message.get("name", ""), "response": payload}
            if message.get("tool_call_id") in native_ids:
                response["id"] = message["tool_call_id"]
            part = {"function_response": response}
            if contents and all("function_response" in p for p in contents[-1]["parts"]):
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
        else:
            if pending:
                raise ValueError("Missing tool results before next user turn")
            contents.append({"role": "user", "parts": [{"text": message.get("content", "")}]})
    if pending:
        raise ValueError("Missing tool results")
    return contents
