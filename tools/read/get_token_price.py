"""Tool: get_token_price – Get current price, 24h change, and historical chart data."""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field

from services.price_service import PriceService
from tools.base import BaseTool, RiskLevel, ToolContext, ToolResult
from tools.registry import register_tool

logger = logging.getLogger(__name__)


class GetTokenPriceInput(BaseModel):
    symbol: str = Field(
        default="ETH",
        description="Cryptocurrency token symbol, e.g. 'ETH', 'BTC', 'LINK'.",
    )
    timeframe: str = Field(
        default="24h",
        description="Timeframe for historical price chart: '1h', '24h', '7d', '30d'.",
    )
    source: str = Field(
        default="coingecko",
        description="Price data provider: 'coingecko' (market data with chart) or 'chainlink' (on-chain Sepolia oracle).",
    )


@register_tool
class GetTokenPrice(BaseTool):
    name = "get_token_price"
    description = (
        "Get current market price, 24h percentage change, and historical chart data for reference assets "
        "(ETH, BTC, LINK) from CoinGecko or Chainlink Sepolia oracle. Returns structured price data and "
        "a [CHART:<SYMBOL>:<TIMEFRAME>] marker for frontend chart rendering. Note: Prices reflect real-world "
        "reference assets; Sepolia testnet tokens have no real-world monetary value."
    )
    risk_level = RiskLevel.READ
    args_schema = GetTokenPriceInput

    async def run(self, validated: GetTokenPriceInput, ctx: ToolContext) -> ToolResult:
        symbol = (validated.symbol or "ETH").upper()
        timeframe = (validated.timeframe or "24h").lower()
        source = (validated.source or "coingecko").lower()

        cache_key = f"token_price_{symbol}_{timeframe}_{source}"
        cached = ctx.cache_get(cache_key, ttl=30.0)
        if cached is not None:
            return ToolResult.success(cached, source="cache")

        try:
            # Retrieve or initialize PriceService
            price_service = getattr(ctx.blockchain, "_price_service", None)
            if not isinstance(price_service, PriceService):
                # Try getting rpc url if available
                rpc_url = getattr(ctx.blockchain, "rpc_url", None)
                price_service = PriceService(rpc_url=rpc_url)
                try:
                    ctx.blockchain._price_service = price_service
                except Exception:
                    pass

            data = await price_service.get_token_price(
                symbol=symbol, timeframe=timeframe, source=source
            )
            ctx.cache_set(cache_key, data)
            return ToolResult.success(data)
        except Exception as e:
            logger.exception("Error executing get_token_price for %s", symbol)
            return ToolResult.failure(f"Failed to fetch token price for {symbol}: {e}")

