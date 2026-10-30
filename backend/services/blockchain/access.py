"""Capabilities required by synchronous RPC adapters; no facade dependency."""

from typing import Any, Protocol

from web3 import Web3

from backend.network.network_manager import NetworkManager


class RpcAccess(Protocol):
    @property
    def w3(self) -> Web3: ...

    @property
    def chain_id(self) -> int: ...


class ContractAccess(RpcAccess, Protocol):
    network_manager: NetworkManager

    def validate_and_checksum_address(self, address: str) -> str: ...

    def get_erc20_contract(
        self, token_address: str, custom_abi: list[dict[str, Any]] | None = None
    ) -> Any: ...


class BuilderAccess(ContractAccess, Protocol):
    def get_gas_price(self) -> dict[str, Any]: ...
