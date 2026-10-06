"""Blockchain service interface and implementations.

``BlockchainService`` is a Protocol – teammates can swap the implementation
without modifying tool code.

Provided implementations:
- ``Web3BlockchainService``: real connection via web3.py (Sepolia).
- ``MockBlockchainService``: deterministic mock for unit tests.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ── Protocol ──────────────────────────────────────────────────────────


@runtime_checkable
class BlockchainService(Protocol):
    """Interface for all blockchain interactions.

    Teammates (blockchain module) can provide their own implementation.
    Tools depend on this interface only – never on web3 directly.
    """

    async def get_balance(self, address: str) -> int:
        """Native balance in wei."""
        ...

    async def get_erc20_balance(self, token_address: str, wallet_address: str) -> int:
        """ERC-20 token balance (raw, no decimal adjustment)."""
        ...

    async def get_token_info(self, token_address: str) -> dict[str, Any]:
        """Return {name, symbol, decimals, total_supply} for an ERC-20 token."""
        ...

    async def get_transaction(self, tx_hash: str) -> dict[str, Any]:
        """Transaction details by hash."""
        ...

    async def get_block(self, block_identifier: int | str) -> dict[str, Any]:
        """Block information."""
        ...

    async def get_gas_price(self) -> int:
        """Current gas price in wei."""
        ...

    async def estimate_gas(self, tx: dict[str, Any]) -> int:
        """Estimated gas units for a transaction."""
        ...

    async def call(self, tx: dict[str, Any]) -> bytes:
        """``eth_call`` – simulate a transaction without broadcasting."""
        ...

    async def send_raw_transaction(self, signed_tx: bytes) -> str:
        """Broadcast a signed transaction. Returns tx hash hex."""
        ...

    async def get_transaction_count(self, address: str) -> int:
        """Nonce for address."""
        ...

    async def get_chain_id(self) -> int:
        """Return the chain ID of the connected network."""
        ...

    async def read_contract(
        self,
        contract_address: str,
        abi: list[dict[str, Any]],
        function_name: str,
        args: list[Any],
    ) -> Any:
        """Call a view/pure function on a contract."""
        ...


# ── Web3 implementation ──────────────────────────────────────────────


class Web3BlockchainService:
    """Real blockchain service backed by web3.py.

    Connects to a Sepolia RPC endpoint.  Requires ``SEPOLIA_RPC_URL`` and
    ``WALLET_PRIVATE_KEY`` environment variables.
    """

    def __init__(self, rpc_url: str, private_key: str = "") -> None:
        from web3 import AsyncHTTPProvider, AsyncWeb3

        self._w3 = AsyncWeb3(AsyncHTTPProvider(rpc_url))
        self._private_key = private_key
        logger.info("Web3BlockchainService connected to %s", rpc_url)

    @property
    def w3(self) -> Any:
        return self._w3

    async def get_balance(self, address: str) -> int:
        return await self._w3.eth.get_balance(self._w3.to_checksum_address(address))

    async def get_erc20_balance(self, token_address: str, wallet_address: str) -> int:
        from config.settings import load_abi

        abi = load_abi("erc20.json")
        contract = self._w3.eth.contract(
            address=self._w3.to_checksum_address(token_address), abi=abi
        )
        return await contract.functions.balanceOf(
            self._w3.to_checksum_address(wallet_address)
        ).call()

    async def get_token_info(self, token_address: str) -> dict[str, Any]:
        from config.settings import load_abi

        abi = load_abi("erc20.json")
        addr = self._w3.to_checksum_address(token_address)
        contract = self._w3.eth.contract(address=addr, abi=abi)
        name = await contract.functions.name().call()
        symbol = await contract.functions.symbol().call()
        decimals = await contract.functions.decimals().call()
        total_supply = await contract.functions.totalSupply().call()
        return {
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "total_supply": total_supply,
        }

    async def get_transaction(self, tx_hash: str) -> dict[str, Any]:
        tx = await self._w3.eth.get_transaction(tx_hash)
        return dict(tx)

    async def get_block(self, block_identifier: int | str) -> dict[str, Any]:
        block = await self._w3.eth.get_block(block_identifier)
        return dict(block)

    async def get_gas_price(self) -> int:
        return await self._w3.eth.gas_price

    async def estimate_gas(self, tx: dict[str, Any]) -> int:
        return await self._w3.eth.estimate_gas(tx)

    async def call(self, tx: dict[str, Any]) -> bytes:
        return await self._w3.eth.call(tx)

    async def send_raw_transaction(self, signed_tx: bytes) -> str:
        tx_hash = await self._w3.eth.send_raw_transaction(signed_tx)
        return tx_hash.hex()

    async def get_transaction_count(self, address: str) -> int:
        return await self._w3.eth.get_transaction_count(
            self._w3.to_checksum_address(address)
        )

    async def get_chain_id(self) -> int:
        return await self._w3.eth.chain_id

    async def read_contract(
        self,
        contract_address: str,
        abi: list[dict[str, Any]],
        function_name: str,
        args: list[Any],
    ) -> Any:
        addr = self._w3.to_checksum_address(contract_address)
        contract = self._w3.eth.contract(address=addr, abi=abi)
        fn = contract.functions[function_name](*args)
        return await fn.call()


# ── Mock implementation (for testing) ─────────────────────────────────


class MockBlockchainData(BaseModel):
    """Pre-configured data for ``MockBlockchainService``."""

    balances: dict[str, int] = {}  # address → wei
    erc20_balances: dict[str, dict[str, int]] = {}  # token → {wallet → raw balance}
    token_info: dict[str, dict[str, Any]] = {}  # token → {name, symbol, ...}
    transactions: dict[str, dict[str, Any]] = {}  # tx_hash → tx data
    blocks: dict[str, dict[str, Any]] = {}  # block_id (str) → block data
    gas_price: int = 20_000_000_000  # 20 gwei
    chain_id: int = 11155111  # Sepolia
    nonces: dict[str, int] = {}  # address → nonce
    call_results: dict[str, bytes] = {}  # tx_data_hash → result bytes
    contract_results: dict[str, Any] = {}  # "address:function" → result
    sent_transactions: list[bytes] = []  # for asserting in tests


class MockBlockchainService:
    """Deterministic mock for unit testing. Never hits the network."""

    def __init__(self, data: MockBlockchainData | None = None) -> None:
        self.data = data or MockBlockchainData()

    async def get_balance(self, address: str) -> int:
        return self.data.balances.get(address.lower(), 0)

    async def get_erc20_balance(self, token_address: str, wallet_address: str) -> int:
        token_balances = self.data.erc20_balances.get(token_address.lower(), {})
        return token_balances.get(wallet_address.lower(), 0)

    async def get_token_info(self, token_address: str) -> dict[str, Any]:
        info = self.data.token_info.get(token_address.lower())
        if info is None:
            raise ValueError(f"Token not found: {token_address}")
        return info

    async def get_transaction(self, tx_hash: str) -> dict[str, Any]:
        tx = self.data.transactions.get(tx_hash.lower())
        if tx is None:
            raise ValueError(f"Transaction not found: {tx_hash}")
        return tx

    async def get_block(self, block_identifier: int | str) -> dict[str, Any]:
        block = self.data.blocks.get(str(block_identifier))
        if block is None:
            raise ValueError(f"Block not found: {block_identifier}")
        return block

    async def get_gas_price(self) -> int:
        return self.data.gas_price

    async def estimate_gas(self, tx: dict[str, Any]) -> int:
        return 21_000  # standard ETH transfer

    async def call(self, tx: dict[str, Any]) -> bytes:
        return b""  # successful simulation

    async def send_raw_transaction(self, signed_tx: bytes) -> str:
        self.data.sent_transactions.append(signed_tx)
        return "0x" + "ab" * 32  # fake tx hash

    async def get_transaction_count(self, address: str) -> int:
        return self.data.nonces.get(address.lower(), 0)

    async def get_chain_id(self) -> int:
        return self.data.chain_id

    async def read_contract(
        self,
        contract_address: str,
        abi: list[dict[str, Any]],
        function_name: str,
        args: list[Any],
    ) -> Any:
        key = f"{contract_address.lower()}:{function_name}"
        result = self.data.contract_results.get(key)
        if result is None:
            raise ValueError(f"No mock result for {key}")
        return result
