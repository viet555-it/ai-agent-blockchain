"""Protocol regression tests with a mocked SDK; no network or API key."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from agent.llm.gemini import GeminiProvider, _convert_messages
from agent.memory import ConversationMemory


@pytest.mark.asyncio
async def test_native_system_and_signed_function_call_survive_round_trip():
    signature = b"\x00\xffopaque-signature"
    part = types.Part(
        function_call=types.FunctionCall(
            id="call-native", name="get_native_balance", args={"address": "0xabc"}
        ),
        thought_signature=signature,
    )
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))], usage_metadata=None
    )
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=response)
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("test-key", max_output_tokens=256)
    first = await provider.chat(
        [{"role": "system", "content": "READ only"}, {"role": "user", "content": "balance"}]
    )
    request = client.aio.models.generate_content.call_args.kwargs
    assert request["config"].system_instruction == "READ only"
    assert request["config"].max_output_tokens == 256
    assert request["contents"] == [{"role": "user", "parts": [{"text": "balance"}]}]
    memory = ConversationMemory()
    memory.add_assistant(tool_calls=first.tool_calls, provider_metadata=first.provider_metadata)
    memory.add_tool_result(
        "call-native", "get_native_balance", '{"ok":true,"data":{"raw_balance":"1"}}'
    )
    native = _convert_messages(memory.get_messages())
    assert native[0]["parts"][0]["thought_signature"] == signature
    assert native[1]["parts"][0]["function_response"]["id"] == "call-native"
    assert native[1]["parts"][0]["function_response"]["response"]["data"]["raw_balance"] == "1"


@pytest.mark.asyncio
async def test_thought_text_is_not_returned_as_final_answer():
    parts = [types.Part(text="internal deliberation", thought=True), types.Part(text="Answer")]
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=parts))], usage_metadata=None
        )
    )
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("test-key")
    response = await provider.chat([{"role": "user", "content": "hello"}])
    assert response.content == "Answer"
    assert "internal deliberation" not in repr(response)


@pytest.mark.asyncio
async def test_request_cap_prevents_another_sdk_call():
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(candidates=[], usage_metadata=None)
    )
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("test-key", max_calls=1)
    await provider.chat([{"role": "user", "content": "hello"}])
    with pytest.raises(RuntimeError, match="budget"):
        await provider.chat([{"role": "user", "content": "again"}])
    client.aio.models.generate_content.assert_awaited_once()


def test_legacy_history_is_supported_without_inventing_native_ids():
    rows = _convert_messages(
        [
            {
                "role": "assistant",
                "tool_calls": [{"id": "client-id", "name": "read", "arguments": {}}],
            },
            {
                "role": "tool",
                "tool_call_id": "client-id",
                "name": "read",
                "content": "plain result",
            },
        ]
    )
    assert rows[0]["parts"][0]["function_call"]["name"] == "read"
    assert "id" not in rows[1]["parts"][0]["function_response"]
    assert rows[1]["parts"][0]["function_response"]["response"] == {"result": "plain result"}


@pytest.mark.asyncio
async def test_provider_error_does_not_echo_credentials():
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        side_effect=RuntimeError("URL contained secret-key")
    )
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("secret-key")
    with pytest.raises(RuntimeError) as raised:
        await provider.chat([{"role": "user", "content": "hello"}])
    assert "secret-key" not in str(raised.value)
    assert provider.last_error == {"type": "RuntimeError", "http_status": None}


@pytest.mark.asyncio
async def test_success_clears_previous_provider_diagnostic():
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        side_effect=[RuntimeError("temporary"), SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[types.Part(text="OK")]))],
            usage_metadata=None)]
    )
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("fixture")
    with pytest.raises(RuntimeError):
        await provider.chat([{"role": "user", "content": "first"}])
    assert provider.last_error is not None
    await provider.chat([{"role": "user", "content": "second"}])
    assert provider.last_error is None


def test_parallel_results_are_one_response_turn_and_keep_both_ids():
    rows = _convert_messages([
        {"role": "assistant", "tool_calls": [
            {"id": "a", "name": "first"}, {"id": "b", "name": "second"}]},
        {"role": "tool", "tool_call_id": "a", "name": "first", "content": "{}"},
        {"role": "tool", "tool_call_id": "b", "name": "second", "content": "{}"},
    ])
    assert len(rows) == 2
    assert [p["function_response"]["name"] for p in rows[1]["parts"]] == ["first", "second"]


@pytest.mark.parametrize("rows", [
    [{"role": "tool", "tool_call_id": "a", "name": "read", "content": "{}"}],
    [{"role": "assistant", "tool_calls": [{"id": "a", "name": "read"}]}],
    [{"role": "assistant", "tool_calls": [{"id": "a", "name": "read"}]},
     {"role": "tool", "tool_call_id": "a", "name": "other", "content": "{}"}],
])
@pytest.mark.asyncio
async def test_invalid_tool_history_is_rejected_before_network(rows):
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock()
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("fixture")
    with pytest.raises(RuntimeError, match="tool history"):
        await provider.chat(rows)
    client.aio.models.generate_content.assert_not_awaited()
    assert provider.call_count == 0
    assert provider.last_error["reason"] == "INVALID_TOOL_HISTORY"


@pytest.mark.asyncio
async def test_empty_max_tokens_response_has_safe_reason():
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=SimpleNamespace(
        candidates=[SimpleNamespace(content=None, finish_reason=types.FinishReason.MAX_TOKENS)],
        usage_metadata=None))
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("fixture")
    response = await provider.chat([{"role": "user", "content": "hello"}])
    assert response.content is None
    assert provider.last_error["reason"] == "MAX_TOKENS"


@pytest.mark.asyncio
async def test_http_reason_does_not_store_raw_message():
    class ProviderError(Exception):
        code = 400
        message = "function response lacks function call; secret-key in URL"
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(side_effect=ProviderError())
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("secret-key")
    with pytest.raises(RuntimeError):
        await provider.chat([{"role": "user", "content": "hello"}])
    assert provider.last_error["reason"] == "INVALID_TOOL_HISTORY"
    assert "secret-key" not in repr(provider.last_error)


@pytest.mark.asyncio
async def test_all_local_proposal_schemas_are_gemini_compatible_and_validation_stays_strict():
    from pydantic import ValidationError

    from backend.agent.proposal_tools import TokenInput, proposal_tools

    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(candidates=[], usage_metadata=None)
    )
    with patch("google.genai.Client", return_value=client):
        provider = GeminiProvider("test-key")
    tools = [tool.to_gemini_tool() for tool in proposal_tools(MagicMock()).values()]
    originals = repr(tools)
    await provider.chat([{"role": "user", "content": "balance"}], tools)
    declarations = (
        client.aio.models.generate_content.call_args.kwargs["config"].tools[0].function_declarations
    )
    schemas = [item.parameters.model_dump(exclude_none=True) for item in declarations]
    assert "additional_properties" not in repr(schemas)
    assert "default" not in repr(schemas)
    assert schemas[1]["properties"]["token_address"]["nullable"] is True
    assert schemas[1]["required"] == ["to", "amount"]
    assert repr(tools) == originals
    with pytest.raises(ValidationError):
        TokenInput(to="0x123", amount="1", approval=True)
