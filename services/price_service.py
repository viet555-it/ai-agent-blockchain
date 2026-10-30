"""Price tracking service for ETH/USD.

Fetches current and historical ETH prices from CoinGecko, reads the
Chainlink Sepolia ETH/USD oracle, and supports configurable price alerts.

All HTTP calls use ``httpx.AsyncClient``.  An in-memory cache prevents
excessive upstream requests.  When the upstream API is unreachable the
service returns an error object with ``source: None`` — it **never**
fabricates or randomises prices.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── CoinGecko endpoints ──────────────────────────────────────────────

COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_MARKET_CHART = "https://api.coingecko.com/api/v3/coins/ethereum/market_chart"

# ── Chainlink Sepolia ETH/USD aggregator ─────────────────────────────

CHAINLINK_ETH_USD_ADDRESS = "0x694AA1769357215DE4FAC081bf1f309aDC325306"
CHAINLINK_LATEST_ROUND_SELECTOR = "0xfeaf968c"
CHAINLINK_DECIMALS = 8

# Default Sepolia public RPC
DEFAULT_SEPOLIA_RPC = "https://ethereum-sepolia.publicnode.com"

# ── Timeframe presets ────────────────────────────────────────────────

_TIMEFRAME_CONFIG: dict[str, dict[str, Any]] = {
    "1h": {"days": "0.042", "interval": "minutely"},   # ~1 h  → 5-min granularity
    "24h": {"days": "1", "interval": "hourly"},         # 24 h  → 1-hour granularity
    "7d": {"days": "7", "interval": "hourly"},          # 7 d   → ~6-hour (post-sampled)
}

# ── Helpers ──────────────────────────────────────────────────────────


def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _downsample(prices: list[list[float]], step: int) -> list[dict[str, Any]]:
    """Keep every *step*-th entry and normalise to ``{timestamp, price}``."""
    return [
        {"timestamp": int(p[0] / 1000), "price": p[1]}
        for idx, p in enumerate(prices)
        if idx % step == 0
    ]


# ── Cache entry ──────────────────────────────────────────────────────


class _CacheEntry:
    """Simple TTL-based cache entry."""

    __slots__ = ("data", "expires_at")

    def __init__(self, data: Any, ttl: float) -> None:
        self.data = data
        self.expires_at = time.monotonic() + ttl

    @property
    def valid(self) -> bool:
        return time.monotonic() < self.expires_at


# ── PriceService ─────────────────────────────────────────────────────


class PriceService:
    """ETH/USD price tracker with CoinGecko, Chainlink and alert support.

    Parameters
    ----------
    rpc_url:
        Sepolia JSON-RPC endpoint for Chainlink reads.  Falls back to the
        public ``ethereum-sepolia.publicnode.com`` node.
    cache_ttl:
        Seconds before a cached *current price* response is considered stale.
        Historical data uses ``cache_ttl * 2``.
    """

    def __init__(self, rpc_url: str | None = None, cache_ttl: float = 60.0) -> None:
        self._rpc_url: str = rpc_url or DEFAULT_SEPOLIA_RPC
        self._cache_ttl: float = cache_ttl
        self._history_ttl: float = cache_ttl * 2

        # In-memory caches keyed by a descriptive string.
        self._cache: dict[str, _CacheEntry] = {}

        # Price alerts: id → alert dict.
        self._alerts: dict[str, dict[str, Any]] = {}
        # IDs of alerts that have already fired (fire-once semantics).
        self._triggered: set[str] = set()

    # ── Current price ────────────────────────────────────────────────

    async def get_current_price(self) -> dict[str, Any]:
        """Fetch the current ETH/USD price from CoinGecko.

        Returns a dict with keys ``symbol``, ``price_usd``,
        ``change_24h_pct``, ``source``, ``updated_at``, and ``cached``.
        On upstream failure the ``source`` is ``None`` and no fake price is
        returned.
        """
        cache_key = "current_price"
        cached = self._cache.get(cache_key)
        if cached and cached.valid:
            result = dict(cached.data)
            result["cached"] = True
            return result

        params = {
            "ids": "ethereum",
            "vs_currencies": "usd",
            "include_24hr_change": "true",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(COINGECKO_SIMPLE_PRICE, params=params)
                resp.raise_for_status()
                data = resp.json()

            eth = data.get("ethereum", {})
            price_usd = eth.get("usd")
            change_24h = eth.get("usd_24h_change")

            if price_usd is None:
                raise ValueError("Missing price data in CoinGecko response")

            result: dict[str, Any] = {
                "symbol": "ETH",
                "price_usd": float(price_usd),
                "change_24h_pct": round(float(change_24h), 2) if change_24h is not None else None,
                "source": "coingecko",
                "updated_at": _now_iso(),
                "cached": False,
            }
            self._cache[cache_key] = _CacheEntry(result, self._cache_ttl)
            return result

        except Exception:
            logger.exception("Failed to fetch current price from CoinGecko")
            return {
                "symbol": "ETH",
                "price_usd": None,
                "change_24h_pct": None,
                "source": None,
                "updated_at": _now_iso(),
                "cached": False,
                "error": "Failed to fetch price from CoinGecko",
            }

    # ── Historical prices ────────────────────────────────────────────

    async def get_price_history(self, timeframe: str = "24h") -> dict[str, Any]:
        """Fetch historical ETH/USD prices for the given *timeframe*.

        Supported timeframes: ``1h``, ``24h``, ``7d``.
        """
        if timeframe not in _TIMEFRAME_CONFIG:
            return {
                "symbol": "ETH",
                "timeframe": timeframe,
                "prices": [],
                "source": None,
                "updated_at": _now_iso(),
                "error": f"Invalid timeframe '{timeframe}'. Must be one of: 1h, 24h, 7d",
            }

        cache_key = f"history_{timeframe}"
        cached = self._cache.get(cache_key)
        if cached and cached.valid:
            return cached.data

        cfg = _TIMEFRAME_CONFIG[timeframe]
        params: dict[str, str] = {
            "vs_currency": "usd",
            "days": cfg["days"],
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(COINGECKO_MARKET_CHART, params=params)
                resp.raise_for_status()
                data = resp.json()

            raw_prices: list[list[float]] = data.get("prices", [])

            # Down-sample 7d data to ~6-hour intervals (CoinGecko returns
            # hourly data for day ranges ≤ 90).
            step = 6 if timeframe == "7d" else 1
            prices = _downsample(raw_prices, step)

            result: dict[str, Any] = {
                "symbol": "ETH",
                "timeframe": timeframe,
                "prices": prices,
                "source": "coingecko",
                "updated_at": _now_iso(),
            }
            self._cache[cache_key] = _CacheEntry(result, self._history_ttl)
            return result

        except Exception:
            logger.exception("Failed to fetch price history from CoinGecko")
            return {
                "symbol": "ETH",
                "timeframe": timeframe,
                "prices": [],
                "source": None,
                "updated_at": _now_iso(),
                "error": "Failed to fetch price history from CoinGecko",
            }

    # ── Multi-currency comparison ────────────────────────────────────

    async def get_comparison(self) -> dict[str, Any]:
        """Fetch ETH price in USD, EUR, JPY and BTC from CoinGecko."""
        cache_key = "comparison"
        cached = self._cache.get(cache_key)
        if cached and cached.valid:
            return cached.data

        params = {
            "ids": "ethereum",
            "vs_currencies": "usd,eur,jpy,btc",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(COINGECKO_SIMPLE_PRICE, params=params)
                resp.raise_for_status()
                data = resp.json()

            eth = data.get("ethereum", {})
            result: dict[str, Any] = {
                "base": "ETH",
                "rates": {
                    "usd": eth.get("usd"),
                    "eur": eth.get("eur"),
                    "jpy": eth.get("jpy"),
                    "btc": eth.get("btc"),
                },
                "source": "coingecko",
                "updated_at": _now_iso(),
            }
            self._cache[cache_key] = _CacheEntry(result, self._cache_ttl)
            return result

        except Exception:
            logger.exception("Failed to fetch comparison data from CoinGecko")
            return {
                "base": "ETH",
                "rates": {},
                "source": None,
                "updated_at": _now_iso(),
                "error": "Failed to fetch comparison data from CoinGecko",
            }

    # ── Chainlink Sepolia oracle ─────────────────────────────────────

    async def get_chainlink_price(self) -> dict[str, Any] | None:
        """Read the latest ETH/USD price from the Chainlink Sepolia aggregator.

        Uses a raw ``eth_call`` JSON-RPC request so there is no dependency on
        ``web3.py`` for this read-only query.  Returns ``None`` on any error.
        """
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [
                {
                    "to": CHAINLINK_ETH_USD_ADDRESS,
                    "data": CHAINLINK_LATEST_ROUND_SELECTOR,
                },
                "latest",
            ],
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self._rpc_url, json=payload)
                resp.raise_for_status()
                rpc_result = resp.json()

            hex_data: str = rpc_result.get("result", "")
            if not hex_data or hex_data == "0x" or len(hex_data) < 66:
                logger.warning("Chainlink returned empty or short result: %s", hex_data)
                return None

            return self._parse_chainlink_response(hex_data)

        except Exception:
            logger.exception("Failed to read Chainlink Sepolia oracle")
            return None

    @staticmethod
    def _parse_chainlink_response(hex_data: str) -> dict[str, Any]:
        """Decode the ABI-encoded ``latestRoundData()`` return value.

        ``latestRoundData()`` returns five ``int256`` words:
        ``(roundId, answer, startedAt, updatedAt, answeredInRound)``.
        Each word is 32 bytes (64 hex chars).  The ``answer`` (word 1)
        is the price with ``CHAINLINK_DECIMALS`` decimals.
        """
        raw = hex_data[2:]  # strip leading "0x"

        round_id = int(raw[0:64], 16)
        answer = int(raw[64:128], 16)
        # startedAt = raw[128:192]  # not needed
        updated_at_ts = int(raw[192:256], 16)
        # answeredInRound = raw[256:320]  # not needed

        price_usd = answer / (10 ** CHAINLINK_DECIMALS)
        updated_at = datetime.fromtimestamp(updated_at_ts, tz=timezone.utc).isoformat()

        return {
            "pair": "ETH/USD",
            "price_usd": price_usd,
            "round_id": round_id,
            "source": "chainlink_sepolia",
            "updated_at": updated_at,
            "decimals": CHAINLINK_DECIMALS,
        }

    # ── Price alerts ─────────────────────────────────────────────────

    def add_alert(self, direction: str, threshold: float) -> dict[str, Any]:
        """Create a new price alert.

        Parameters
        ----------
        direction:
            ``"above"`` or ``"below"``.
        threshold:
            USD price that triggers the alert.

        Returns
        -------
        dict
            The newly created alert object.
        """
        if direction not in ("above", "below"):
            raise ValueError(f"direction must be 'above' or 'below', got '{direction}'")

        alert_id = f"alert-{uuid.uuid4().hex[:12]}"
        alert: dict[str, Any] = {
            "id": alert_id,
            "pair": "ETH/USD",
            "direction": direction,
            "threshold": threshold,
            "triggered": False,
            "created_at": _now_iso(),
        }
        self._alerts[alert_id] = alert
        logger.info("Price alert created: %s %s $%.2f", alert_id, direction, threshold)
        return dict(alert)

    def check_alerts(self, current_price: float) -> list[dict[str, Any]]:
        """Evaluate all alerts against *current_price*.

        Each alert fires at most once.  Once triggered it is marked
        ``triggered: True`` and will not fire again unless reset.

        Returns the list of *newly* triggered alerts.
        """
        newly_triggered: list[dict[str, Any]] = []

        for alert_id, alert in self._alerts.items():
            if alert_id in self._triggered:
                continue

            fired = False
            if alert["direction"] == "above" and current_price >= alert["threshold"]:
                fired = True
            elif alert["direction"] == "below" and current_price <= alert["threshold"]:
                fired = True

            if fired:
                self._triggered.add(alert_id)
                alert["triggered"] = True
                newly_triggered.append(dict(alert))
                logger.info(
                    "Alert %s triggered: %s %s $%.2f (price=$%.2f)",
                    alert_id,
                    alert["direction"],
                    alert["pair"],
                    alert["threshold"],
                    current_price,
                )

        return newly_triggered

    def get_alerts(self) -> list[dict[str, Any]]:
        """Return all registered alerts (triggered or not)."""
        return [dict(a) for a in self._alerts.values()]

    def remove_alert(self, alert_id: str) -> bool:
        """Delete an alert by ID.  Returns ``True`` if found and removed."""
        if alert_id in self._alerts:
            del self._alerts[alert_id]
            self._triggered.discard(alert_id)
            logger.info("Price alert removed: %s", alert_id)
            return True
        return False
