"""Shared pytest fixtures for the test suite."""

from __future__ import annotations

import pytest

from services.blockchain import MockBlockchainData, MockBlockchainService
from services.retriever import NullRetriever
from tools.registry import clear_registry

# ── Fixture: clean tool registry per test ─────────────────────────────


@pytest.fixture(autouse=True)
def _clean_registry():
    """Clear the global tool registry before each test to avoid leakage."""
    clear_registry()
    yield
    clear_registry()


# ── Fixture: mock blockchain service ──────────────────────────────────


@pytest.fixture()
def mock_blockchain() -> MockBlockchainService:
    """Provide a ``MockBlockchainService`` pre-loaded with demo data."""
    data = MockBlockchainData(
        balances={
            "0x742d35cc6634c0532925a3b844bc9e7595f2bd68": 5_000_000_000_000_000_000,  # 5 ETH
            "0x267be1c1d684f78cb4f6a176c4911b741e4ffdc0": 1_000_000_000_000_000_000,  # 1 ETH
        },
        erc20_balances={
            "0xtoken1": {
                "0x742d35cc6634c0532925a3b844bc9e7595f2bd68": 1000_000_000,  # 1000 USDC (6 dec)
            }
        },
        token_info={
            "0xtoken1": {
                "name": "USD Coin",
                "symbol": "USDC",
                "decimals": 6,
                "total_supply": 1_000_000_000_000_000,
            }
        },
        transactions={
            "0x" + "ab" * 32: {
                "hash": "0x" + "ab" * 32,
                "from": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD68",
                "to": "0x267be1C1D684F78cb4F6a176C4911b741E4Ffdc0",
                "value": 1_000_000_000_000_000_000,
                "gas": 21000,
                "blockNumber": 12345,
            }
        },
        blocks={
            "12345": {
                "number": 12345,
                "timestamp": 1700000000,
                "transactions": ["0x" + "ab" * 32],
                "gasUsed": 21000,
            },
            "latest": {
                "number": 99999,
                "timestamp": 1700001000,
                "transactions": [],
                "gasUsed": 0,
            },
        },
        gas_price=20_000_000_000,  # 20 gwei
        chain_id=11155111,  # Sepolia
    )
    return MockBlockchainService(data)


# ── Fixture: null retriever ───────────────────────────────────────────


@pytest.fixture()
def null_retriever() -> NullRetriever:
    return NullRetriever()
