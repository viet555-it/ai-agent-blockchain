"""Etherscan API client for transaction history.

Wraps Etherscan API behind an interface so teammates can swap it with
TheGraph, Alchemy, or another provider without modifying tool code.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

ETHERSCAN_SEPOLIA_API = "https://api-sepolia.etherscan.io/api"


@runtime_checkable
class TransactionHistoryProvider(Protocol):
    """Interface for fetching transaction history."""

    async def get_transactions(
        self, address: str, *, page: int = 1, limit: int = 20
    ) -> list[dict[str, Any]]: ...


class EtherscanClient:
    """Etherscan Sepolia API client (free tier).

    Requires ``ETHERSCAN_API_KEY`` environment variable.
    Free tier limits: 5 req/s, max 10k records.
    """

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def get_transactions(
        self, address: str, *, page: int = 1, limit: int = 20
    ) -> list[dict[str, Any]]:
        params = {
            "module": "account",
            "action": "txlist",
            "address": address,
            "startblock": 0,
            "endblock": 99999999,
            "page": page,
            "offset": min(limit, 100),
            "sort": "desc",
            "apikey": self._api_key,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(ETHERSCAN_SEPOLIA_API, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "1":
            msg = data.get("message", "Unknown Etherscan error")
            if "No transactions found" in msg:
                return []
            raise RuntimeError(f"Etherscan API error: {msg}")

        return data.get("result", [])


class NullTransactionHistoryProvider:
    """No-op provider when Etherscan API key is not configured."""

    async def get_transactions(
        self, address: str, *, page: int = 1, limit: int = 20
    ) -> list[dict[str, Any]]:
        raise RuntimeError(
            "Transaction history is not available: ETHERSCAN_API_KEY is not configured. "
            "Set ETHERSCAN_API_KEY in .env to enable this feature."
        )
