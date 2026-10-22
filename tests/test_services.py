"""Tests for MockBlockchainService and service interfaces."""

from __future__ import annotations

# pyrefly: ignore [missing-import]
import pytest

from services.blockchain import (
    BlockchainService,
    MockBlockchainData,
    MockBlockchainService,
)
from services.retriever import NullRetriever, Retriever

# ── MockBlockchainService tests ───────────────────────────────────────


class TestMockBlockchainService:
    @pytest.fixture()
    def svc(self) -> MockBlockchainService:
        data = MockBlockchainData(
            balances={"0xaaa": 10**18},
            erc20_balances={"0xtoken": {"0xaaa": 500}},
            token_info={
                "0xtoken": {
                    "name": "Test",
                    "symbol": "TST",
                    "decimals": 18,
                    "total_supply": 10**24,
                }
            },
            gas_price=30_000_000_000,
            chain_id=11155111,
        )
        return MockBlockchainService(data)

    async def test_get_balance(self, svc: MockBlockchainService):
        assert await svc.get_balance("0xAAA") == 10**18

    async def test_get_balance_unknown(self, svc: MockBlockchainService):
        assert await svc.get_balance("0xBBB") == 0

    async def test_get_erc20_balance(self, svc: MockBlockchainService):
        assert await svc.get_erc20_balance("0xTOKEN", "0xAAA") == 500

    async def test_get_token_info(self, svc: MockBlockchainService):
        info = await svc.get_token_info("0xTOKEN")
        assert info["symbol"] == "TST"
        assert info["decimals"] == 18

    async def test_get_token_info_not_found(self, svc: MockBlockchainService):
        with pytest.raises(ValueError, match="Token not found"):
            await svc.get_token_info("0xUNKNOWN")

    async def test_get_gas_price(self, svc: MockBlockchainService):
        assert await svc.get_gas_price() == 30_000_000_000

    async def test_get_chain_id(self, svc: MockBlockchainService):
        assert await svc.get_chain_id() == 11155111

    async def test_estimate_gas(self, svc: MockBlockchainService):
        gas = await svc.estimate_gas({"to": "0x1", "value": 100})
        assert gas == 21_000

    async def test_call_returns_bytes(self, svc: MockBlockchainService):
        result = await svc.call({"to": "0x1"})
        assert isinstance(result, bytes)

    async def test_send_raw_transaction(self, svc: MockBlockchainService):
        tx_hash = await svc.send_raw_transaction(b"\x01\x02")
        assert tx_hash.startswith("0x")
        assert len(svc.data.sent_transactions) == 1

    async def test_get_transaction_count(self, svc: MockBlockchainService):
        assert await svc.get_transaction_count("0xAAA") == 0

    async def test_read_contract_missing(self, svc: MockBlockchainService):
        with pytest.raises(ValueError, match="No mock result"):
            await svc.read_contract("0xcontract", [], "balanceOf", ["0xaaa"])


# ── Protocol conformance tests ────────────────────────────────────────


class TestProtocolConformance:
    def test_mock_is_blockchain_service(self):
        """MockBlockchainService should satisfy the BlockchainService protocol."""
        svc = MockBlockchainService()
        assert isinstance(svc, BlockchainService)

    def test_null_retriever_is_retriever(self):
        """NullRetriever should satisfy the Retriever protocol."""
        ret = NullRetriever()
        assert isinstance(ret, Retriever)


# ── NullRetriever tests ──────────────────────────────────────────────


class TestNullRetriever:
    async def test_returns_empty(self):
        ret = NullRetriever()
        chunks = await ret.retrieve("test query", k=3)
        assert chunks == []
