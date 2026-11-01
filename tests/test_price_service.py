"""Unit tests for PriceService: CoinGecko, Chainlink parsing, cache and alerts."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.price_service import PriceService


@pytest.mark.asyncio
async def test_cache_returns_same_data_within_ttl():
    service = PriceService(cache_ttl=60.0)

    mock_response = {
        "ethereum": {
            "usd": 2500.50,
            "usd_24h_change": 2.35,
        }
    }

    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_response
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        # First call fetches from API
        res1 = await service.get_current_price()
        assert res1["source"] == "coingecko"
        assert res1["price_usd"] == 2500.50
        assert res1["cached"] is False
        assert mock_get.call_count == 1

        # Second call hits cache
        res2 = await service.get_current_price()
        assert res2["price_usd"] == 2500.50
        assert res2["cached"] is True
        # Upstream was not called again
        assert mock_get.call_count == 1


@pytest.mark.asyncio
async def test_api_error_returns_null_source_no_fake_price():
    """Acceptance criterion: Lỗi API không sinh giá giả."""
    service = PriceService(cache_ttl=60.0)

    with patch("httpx.AsyncClient.get", side_effect=Exception("CoinGecko 429 Rate Limit")):
        res = await service.get_current_price()
        assert res["source"] is None
        assert res["price_usd"] is None
        assert res["change_24h_pct"] is None
        assert "error" in res


@pytest.mark.asyncio
async def test_alert_triggers_once():
    """Acceptance criterion: Cảnh báo không lặp liên tục."""
    service = PriceService()
    alert = service.add_alert(direction="above", threshold=2500.0)
    alert_id = alert["id"]

    # Price at 2400: alert should NOT trigger
    fired = service.check_alerts(2400.0)
    assert len(fired) == 0

    # Price crosses to 2550: alert should trigger ONCE
    fired = service.check_alerts(2550.0)
    assert len(fired) == 1
    assert fired[0]["id"] == alert_id
    assert fired[0]["triggered"] is True

    # Price stays at 2600: alert should NOT trigger again (fire-once semantics)
    fired_again = service.check_alerts(2600.0)
    assert len(fired_again) == 0


def test_alert_remove():
    service = PriceService()
    alert = service.add_alert(direction="below", threshold=2000.0)
    assert len(service.get_alerts()) == 1
    removed = service.remove_alert(alert["id"])
    assert removed is True
    assert len(service.get_alerts()) == 0
    assert service.remove_alert("non-existent") is False


@pytest.mark.asyncio
async def test_history_timeframe_validation():
    """Acceptance criterion: Biểu đồ đổi đúng khung (1h, 24h, 7d)."""
    service = PriceService()
    # Invalid timeframe
    bad = await service.get_price_history("1y")
    assert bad["source"] is None
    assert "Invalid timeframe" in bad["error"]

    # Valid timeframe mock
    mock_history = {
        "prices": [
            [1730000000000, 2500.0],
            [1730003600000, 2510.0],
        ]
    }
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = mock_history
        mock_resp.raise_for_status.return_value = None
        mock_get.return_value = mock_resp

        for tf in ("1h", "24h", "7d"):
            res = await service.get_price_history(tf)
            assert res["source"] == "coingecko"
            assert res["timeframe"] == tf
            assert len(res["prices"]) > 0


def test_chainlink_parse():
    """Test decoding Chainlink Sepolia latestRoundData() ABI hex."""
    service = PriceService()
    # 5 words: roundId=1, answer=250000000000 ($2500.00), startedAt=0, updatedAt=1730332800, answeredInRound=1
    hex_data = (
        "0x"
        + (1).to_bytes(32, "big").hex()
        + (250000000000).to_bytes(32, "big").hex()
        + (1730332700).to_bytes(32, "big").hex()
        + (1730332800).to_bytes(32, "big").hex()
        + (1).to_bytes(32, "big").hex()
    )
    parsed = service._parse_chainlink_response(hex_data)
    assert parsed["pair"] == "ETH/USD"
    assert parsed["price_usd"] == 2500.0
    assert parsed["round_id"] == 1
    assert parsed["source"] == "chainlink_sepolia"
    assert parsed["decimals"] == 8
