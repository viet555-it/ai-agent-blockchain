"""Compatibility facade for synchronous blockchain reads, preparation and execution."""

from decimal import Decimal
from typing import Any

from eth_account import Account
from web3 import Web3

from backend.network.network_manager import NetworkManager
from backend.services.blockchain import reads, signer, simulation, transaction_builder
from backend.services.blockchain.abi import STANDARD_ERC20_ABI as STANDARD_ERC20_ABI


class BlockchainService:
    """Own provider configuration and retain the existing synchronous service API."""

    def __init__(
        self,
        w3: Web3 | None = None,
        chain_id: int | None = None,
        network_manager: NetworkManager | None = None,
    ):
        self.network_manager = network_manager or NetworkManager()
        if w3 is not None:
            self._w3 = w3
            self._rpc_url = getattr(w3.provider, "endpoint_uri", "custom")
            self._chain_id = chain_id or w3.eth.chain_id
        else:
            target_chain = chain_id or self.network_manager.active_chain_id
            self._w3, self._rpc_url = self.network_manager.get_healthy_provider(target_chain)
            self._chain_id = target_chain

    @property
    def w3(self) -> Web3:
        return self._w3

    @property
    def chain_id(self) -> int:
        return self._chain_id

    @property
    def rpc_url(self) -> str:
        return self._rpc_url

    def validate_and_checksum_address(self, address: str) -> str:
        if not Web3.is_address(address):
            raise ValueError(f"Invalid Ethereum address: '{address}'")
        return self._w3.to_checksum_address(address)

    def get_native_balance(self, address: str) -> dict[str, Any]:
        """Fetch native ETH balance with exact decimal conversion."""
        return reads.get_native_balance(self, address)

    def get_erc20_contract(
        self, token_address: str, custom_abi: list[dict[str, Any]] | None = None
    ):
        return reads.get_erc20_contract(self, token_address, custom_abi)

    def get_token_balance(self, token_address: str, wallet_address: str) -> dict[str, Any]:
        """Fetch ERC-20 token balance without float rounding."""
        return reads.get_token_balance(self, token_address, wallet_address)

    def get_token_info(self, token_address: str) -> dict[str, Any]:
        """Fetch ERC-20 token metadata."""
        return reads.get_token_info(self, token_address)

    def get_allowance(self, token_address: str, owner: str, spender: str) -> dict[str, Any]:
        """Check current allowance of spender on owner's tokens."""
        return reads.get_allowance(self, token_address, owner, spender)

    def get_transaction(self, tx_hash: str) -> dict[str, Any]:
        return reads.get_transaction(self, tx_hash)

    def get_transaction_receipt(self, tx_hash: str) -> dict[str, Any]:
        return reads.get_transaction_receipt(self, tx_hash)

    def get_block(self, block_identifier: int | str = "latest") -> dict[str, Any]:
        return reads.get_block(self, block_identifier)

    def get_gas_price(self) -> dict[str, Any]:
        return reads.get_gas_price(self)

    def read_contract(
        self, contract_address: str, abi: list[dict[str, Any]], function_name: str, *args: Any
    ) -> Any:
        return reads.read_contract(self, contract_address, abi, function_name, *args)

    def simulate_transfer(
        self,
        sender: str,
        recipient: str,
        amount_token: str | int,
        token_address: str | None = None,
        spender: str | None = None,
    ) -> dict[str, Any]:
        """Simulate real token transfer using eth_call.

        Validates caller, balances, and guardrails without modifying on-chain state.
        Contract reverts return isValid=False with exact revert reason.
        """
        return simulation.simulate_transfer(
            self, sender, recipient, amount_token, token_address, spender
        )

    def prepare_native_transfer(
        self,
        from_address: str,
        to_address: str,
        amount_eth: str | int | Decimal,
        priority: str = "medium",
    ) -> dict[str, Any]:
        return transaction_builder.prepare_native_transfer(
            self, from_address, to_address, amount_eth, priority
        )

    def prepare_token_transfer(
        self, token_address: str, from_address: str, to_address: str, amount_token: str | int
    ) -> dict[str, Any]:
        return transaction_builder.prepare_token_transfer(
            self, token_address, from_address, to_address, amount_token
        )

    def prepare_token_approve(
        self, token_address: str, owner_address: str, spender_address: str, amount_token: str | int
    ) -> dict[str, Any]:
        return transaction_builder.prepare_token_approve(
            self, token_address, owner_address, spender_address, amount_token
        )

    def prepare_faucet_claim(
        self, token_address: str, recipient_address: str, amount_token: str | int
    ) -> dict[str, Any]:
        return transaction_builder.prepare_faucet_claim(
            self, token_address, recipient_address, amount_token
        )

    def sign_and_send_transaction(self, tx_dict: dict[str, Any], private_key: str) -> str:
        """Sign and broadcast transaction using a private key."""
        return signer.sign_and_send_transaction(self, tx_dict, private_key)

    def wait_for_receipt(
        self, tx_hash: str, timeout: int = 120, poll_latency: float = 1.0
    ) -> dict[str, Any]:
        """Wait for transaction receipt."""
        return signer.wait_for_receipt(self, tx_hash, timeout, poll_latency)

    def execute_faucet_claim(
        self, token_address: str, recipient_private_key: str, amount_token: str | int
    ) -> dict[str, Any]:
        account = Account.from_key(recipient_private_key)
        prep = self.prepare_faucet_claim(token_address, account.address, amount_token)
        tx_hash = self.sign_and_send_transaction(prep["transaction"], recipient_private_key)
        receipt = self.wait_for_receipt(tx_hash)
        return {
            "tx_hash": tx_hash,
            "receipt": receipt,
            "status": "success" if receipt["status"] == 1 else "reverted",
        }

    def execute_token_transfer(
        self,
        token_address: str,
        sender_private_key: str,
        recipient_address: str,
        amount_token: str | int,
    ) -> dict[str, Any]:
        account = Account.from_key(sender_private_key)
        prep = self.prepare_token_transfer(
            token_address, account.address, recipient_address, amount_token
        )
        tx_hash = self.sign_and_send_transaction(prep["transaction"], sender_private_key)
        receipt = self.wait_for_receipt(tx_hash)
        return {
            "tx_hash": tx_hash,
            "receipt": receipt,
            "status": "success" if receipt["status"] == 1 else "reverted",
        }

    def execute_token_approve(
        self,
        token_address: str,
        owner_private_key: str,
        spender_address: str,
        amount_token: str | int,
    ) -> dict[str, Any]:
        account = Account.from_key(owner_private_key)
        prep = self.prepare_token_approve(
            token_address, account.address, spender_address, amount_token
        )
        tx_hash = self.sign_and_send_transaction(prep["transaction"], owner_private_key)
        receipt = self.wait_for_receipt(tx_hash)
        return {
            "tx_hash": tx_hash,
            "receipt": receipt,
            "status": "success" if receipt["status"] == 1 else "reverted",
        }
