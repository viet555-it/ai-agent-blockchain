"""Tests for Agent natural chat, language synchronization, and get_token_price tool."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.agent.language import (
    detect_query_language,
    get_localized_message,
    is_conversational_query,
    resolve_language,
)
from backend.agent.prompts import read_system_prompt
from backend.agent.response_mapper import map_agent_response
from backend.agent.models import TimelineStep
from backend.rag.rag_adapter import RAGSearchResult
from services.price_service import PriceService
from tools.base import ToolContext
from tools.read.get_token_price import GetTokenPrice, GetTokenPriceInput


# ── Language Detection & Resolution Tests ─────────────────────────────


def test_detect_language_vietnamese():
    assert detect_query_language("Xin chào bạn, hôm nay thế nào?") == "vi"
    assert detect_query_language("Số dư ví của tôi còn bao nhiêu?") == "vi"
    assert detect_query_language("giá ETH tuần này?") == "vi"
    assert detect_query_language("kiểm tra phí gas") == "vi"
    assert detect_query_language("chuyển 10 AGNT tới ví 0x123") == "vi"


def test_detect_language_english():
    assert detect_query_language("Hello, how are you?") == "en"
    assert detect_query_language("What is the balance of my wallet?") == "en"
    assert detect_query_language("Check ETH price this week") == "en"
    assert detect_query_language("What is gas fee in Ethereum?") == "en"


def test_resolve_language_preference_and_overrides():
    # Explicit user preference
    assert resolve_language("vi", "Hello world") == "vi"
    assert resolve_language("en", "Xin chào bạn") == "en"

    # Query-level override takes highest priority
    assert resolve_language("en", "Giải thích bằng tiếng Việt giúp tôi") == "vi"
    assert resolve_language("vi", "Please explain in English") == "en"

    # Auto mode detects from prompt
    assert resolve_language("auto", "Kiểm tra số dư ví") == "vi"
    assert resolve_language("auto", "Check my wallet balance") == "en"
    assert resolve_language(None, "Xin chào") == "vi"


# ── Conversational & Chat Detection Tests ─────────────────────────────


def test_is_conversational_query():
    # Greetings
    assert is_conversational_query("hello") is True
    assert is_conversational_query("xin chào") is True
    assert is_conversational_query("hi there!") is True
    assert is_conversational_query("chào bạn") is True
    assert is_conversational_query("good morning") is True

    # Identity & capabilities
    assert is_conversational_query("who are you?") is True
    assert is_conversational_query("bạn là ai?") is True
    assert is_conversational_query("bạn làm được gì?") is True
    assert is_conversational_query("what can you do?") is True

    # Courtesy
    assert is_conversational_query("cảm ơn bạn") is True
    assert is_conversational_query("thank you very much") is True

    # Action / Blockchain queries should NOT be conversational
    assert is_conversational_query("Check balance of 0x123") is False
    assert is_conversational_query("Transfer 10 ETH") is False
    assert is_conversational_query("Giá ETH hôm nay") is False


# ── System Prompt Customization Tests ─────────────────────────────────


def test_system_prompt_language_instructions():
    prompt_vi = read_system_prompt(11155111, proposals_enabled=True, language="vi")
    assert "You MUST respond in Vietnamese" in prompt_vi
    assert "CONVERSATIONAL GUIDELINES" in prompt_vi
    assert "MARKET PRICE TRACKING" in prompt_vi
    assert "[CHART:ETH:<timeframe>]" in prompt_vi

    prompt_en = read_system_prompt(11155111, proposals_enabled=True, language="en")
    assert "You MUST respond in English" in prompt_en

    prompt_auto = read_system_prompt(11155111, proposals_enabled=True, language="auto")
    assert "Reply in the same language as the user's message" in prompt_auto


# ── Response Mapper Natural Chat & Language Tests ────────────────────


def test_response_mapper_preserves_natural_chat():
    timeline = [TimelineStep(step_number=1, name="Request received", status="SUCCESS")]
    events = [
        {"type": "final", "data": {"content": "Xin chào! Tôi có thể giúp gì cho bạn hôm nay?"}}
    ]

    rag = RAGSearchResult(query="Xin chào", documents=[], has_relevant_context=False)
    res = map_agent_response(
        events=events,
        query="Xin chào",
        rag=rag,
        request_context={},
        timeline=timeline,
        start=0.0,
        language="vi",
    )

    # Must preserve the natural conversational reply instead of overwriting with doc error
    assert res.reply == "Xin chào! Tôi có thể giúp gì cho bạn hôm nay?"
    assert res.intent == "llm_chat"
    assert res.tool_selected is None


def test_response_mapper_doc_not_found_on_unrelated_topic():
    timeline = [TimelineStep(step_number=1, name="Request received", status="SUCCESS")]
    events = []

    rag_vi = RAGSearchResult(query="tài liệu về hàm fooBarUnknown()", documents=[], has_relevant_context=False)
    res_vi = map_agent_response(
        events=events,
        query="tài liệu về hàm fooBarUnknown()",
        rag=rag_vi,
        request_context={},
        timeline=timeline,
        start=0.0,
        language="vi",
    )
    assert "Chưa tìm thấy tài liệu phù hợp" in res_vi.reply

    rag_en = RAGSearchResult(query="documentation for unknownContractFunction()", documents=[], has_relevant_context=False)
    res_en = map_agent_response(
        events=events,
        query="documentation for unknownContractFunction()",
        rag=rag_en,
        request_context={},
        timeline=timeline,
        start=0.0,
        language="en",
    )
    assert "Chưa tìm thấy tài liệu" in res_en.reply or "No matching documentation" in res_en.reply


# ── get_token_price Tool & Service Tests ──────────────────────────────


@pytest.mark.asyncio
async def test_get_token_price_tool_execution():
    tool = GetTokenPrice()
    assert tool.name == "get_token_price"

    ctx = ToolContext(blockchain=MagicMock(), settings=MagicMock())

    mock_price_data = {
        "type": "coingecko",
        "symbol": "ETH",
        "price_usd": 2850.75,
        "change_24h_pct": 3.12,
        "timeframe": "7d",
        "source": "coingecko",
        "updated_at": "2026-10-31T00:00:00Z",
        "chart_marker": "[CHART:ETH:7d]",
        "history_summary": [{"timestamp": 1700000000, "price": 2800.0}],
        "disclaimer": "Reference only",
    }

    with patch("services.price_service.PriceService.get_token_price", new_callable=AsyncMock) as mock_fn:
        mock_fn.return_value = mock_price_data

        input_data = GetTokenPriceInput(symbol="ETH", timeframe="7d", source="coingecko")
        res = await tool.run(input_data, ctx)

        assert res.ok is True
        assert res.data["symbol"] == "ETH"
        assert res.data["price_usd"] == 2850.75
        assert res.data["chart_marker"] == "[CHART:ETH:7d]"


@pytest.mark.asyncio
async def test_response_mapper_appends_chart_marker_for_eth():
    timeline = [TimelineStep(step_number=1, name="Request received", status="SUCCESS")]
    events = [
        {"type": "tool_call", "data": {"name": "get_token_price", "arguments": {"symbol": "ETH", "timeframe": "7d"}}},
        {
            "type": "tool_result",
            "data": {
                "name": "get_token_price",
                "result": {
                    "ok": True,
                    "data": {
                        "symbol": "ETH",
                        "price_usd": 2700.0,
                        "change_24h_pct": 1.5,
                        "timeframe": "7d",
                        "chart_marker": "[CHART:ETH:7d]",
                    },
                },
            },
        },
        {"type": "final", "data": {"content": "Giá ETH tuần này là $2,700 USD."}},
    ]

    rag = RAGSearchResult(query="giá ETH tuần này?", documents=[], has_relevant_context=False)
    res = map_agent_response(
        events=events,
        query="giá ETH tuần này?",
        rag=rag,
        request_context={},
        timeline=timeline,
        start=0.0,
        language="vi",
    )

    # Chart marker must be appended for frontend interactive rendering
    assert "[CHART:ETH:7d]" in res.reply
    assert res.intent == "llm_price"


@pytest.mark.asyncio
async def test_price_service_multi_token_and_30d():
    service = PriceService()

    # 30d timeframe should be valid
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "prices": [[1700000000000, 3000.0], [1700086400000, 3100.0]]
        }
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        history = await service.get_price_history(timeframe="30d", symbol="ETH")
        assert history["timeframe"] == "30d"
        assert history["source"] == "coingecko"
        assert len(history["prices"]) == 2


@pytest.mark.asyncio
async def test_price_service_chainlink_source():
    service = PriceService()
    mock_chainlink = {
        "pair": "ETH/USD",
        "price_usd": 2650.0,
        "round_id": 12345,
        "source": "chainlink_sepolia",
        "updated_at": "2026-10-31T00:00:00Z",
        "decimals": 8,
    }
    with patch.object(service, "get_chainlink_price", new_callable=AsyncMock) as mock_cl:
        mock_cl.return_value = mock_chainlink
        res = await service.get_token_price(symbol="ETH", source="chainlink")
        assert res["type"] == "chainlink"
        assert res["price_usd"] == 2650.0
        assert res["source"] == "chainlink_sepolia"
