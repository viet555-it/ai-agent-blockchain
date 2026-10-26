"""Comprehensive Blockchain Service for AI Agent interaction, guardrail simulation, and multi-network execution."""
import json
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union
from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError, TransactionNotFound, Web3Exception

from backend.network.network_manager import NetworkManager
from backend.token_amounts import format_token_units, to_token_units, UINT256_MAX

logger = logging.getLogger(__name__)

STANDARD_ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "_owner", "type": "address"},
            {"name": "_spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "payable": False,
        "stateMutability": "view",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transfer",
        "outputs": [{"name": "success", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "_from", "type": "address"},
            {"name": "_to", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "name": "transferFrom",
        "outputs": [{"name": "success", "type": "bool"}],
        "payable": False,
        "stateMutability": "nonpayable",
        "type": "function",
    },
]


class BlockchainService:
    """Production-grade Web3 blockchain service supporting Read, Dry-run simulation, and Write operations."""

    def __init__(
        self,
        w3: Optional[Web3] = None,
        chain_id: Optional[int] = None,
        network_manager: Optional[NetworkManager] = None,
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

    # ── Read Operations ────────────────────────────────────────────────────────

    def get_native_balance(self, address: str) -> Dict[str, Any]:
        """Fetch native ETH balance with exact decimal conversion."""
        target = self.validate_and_checksum_address(address)
        raw_wei = self._w3.eth.get_balance(target)
        formatted_eth = format_token_units(raw_wei, 18)
        config = self.network_manager.get_network_config(self.chain_id)
        return {
            "address": target,
            "chain_id": self.chain_id,
            "network": config.name,
            "balance": formatted_eth,
            "raw_balance": raw_wei,
            "symbol": config.native_currency.symbol,
            "decimals": 18,
        }

    def get_erc20_contract(
        self,
        token_address: str,
        custom_abi: Optional[List[Dict[str, Any]]] = None,
    ):
        target = self.validate_and_checksum_address(token_address)
        abi = custom_abi or STANDARD_ERC20_ABI
        return self._w3.eth.contract(address=target, abi=abi)

    def get_token_balance(self, token_address: str, wallet_address: str) -> Dict[str, Any]:
        """Fetch ERC-20 token balance without float rounding."""
        token_addr = self.validate_and_checksum_address(token_address)
        wallet_addr = self.validate_and_checksum_address(wallet_address)
        contract = self.get_erc20_contract(token_addr)
        raw_balance = contract.functions.balanceOf(wallet_addr).call()
        try:
            decimals = contract.functions.decimals().call()
        except Exception:
            decimals = 18
        try:
            symbol = contract.functions.symbol().call()
        except Exception:
            symbol = "TOKEN"

        return {
            "token_address": token_addr,
            "wallet_address": wallet_addr,
            "balance": format_token_units(raw_balance, decimals),
            "raw_balance": raw_balance,
            "symbol": symbol,
            "decimals": decimals,
            "chain_id": self.chain_id,
        }

    def get_token_info(self, token_address: str) -> Dict[str, Any]:
        """Fetch ERC-20 token metadata."""
        token_addr = self.validate_and_checksum_address(token_address)
        contract = self.get_erc20_contract(token_addr)
        try:
            name = contract.functions.name().call()
        except Exception:
            name = "Unknown Token"
        try:
            symbol = contract.functions.symbol().call()
        except Exception:
            symbol = "TOKEN"
        try:
            decimals = contract.functions.decimals().call()
        except Exception:
            decimals = 18
        try:
            total_supply_raw = contract.functions.totalSupply().call()
            total_supply = format_token_units(total_supply_raw, decimals)
        except Exception:
            total_supply_raw = 0
            total_supply = "0"

        return {
            "token_address": token_addr,
            "name": name,
            "symbol": symbol,
            "decimals": decimals,
            "total_supply": total_supply,
            "raw_total_supply": total_supply_raw,
            "chain_id": self.chain_id,
        }

    def get_allowance(self, token_address: str, owner: str, spender: str) -> Dict[str, Any]:
        """Check current allowance of spender on owner's tokens."""
        token_addr = self.validate_and_checksum_address(token_address)
        owner_addr = self.validate_and_checksum_address(owner)
        spender_addr = self.validate_and_checksum_address(spender)
        contract = self.get_erc20_contract(token_addr)
        raw = contract.functions.allowance(owner_addr, spender_addr).call()
        decimals = contract.functions.decimals().call()
        return {
            "token_address": token_addr,
            "owner": owner_addr,
            "spender": spender_addr,
            "allowance": format_token_units(raw, decimals),
            "raw_allowance": raw,
            "is_unlimited": raw >= UINT256_MAX // 2,
        }

    def get_transaction(self, tx_hash: str) -> Dict[str, Any]:
        tx = self._w3.eth.get_transaction(tx_hash)
        result = dict(tx)
        if "value" in result:
            result["value_eth"] = format_token_units(result["value"], 18)
        return result

    def get_transaction_receipt(self, tx_hash: str) -> Dict[str, Any]:
        try:
            receipt = self._w3.eth.get_transaction_receipt(tx_hash)
            return dict(receipt)
        except TransactionNotFound:
            return {"status": "pending", "tx_hash": tx_hash}

    def get_block(self, block_identifier: Union[int, str] = "latest") -> Dict[str, Any]:
        block = self._w3.eth.get_block(block_identifier)
        return dict(block)

    def get_gas_price(self) -> Dict[str, Any]:
        gas_price_wei = self._w3.eth.gas_price
        latest_block = self._w3.eth.get_block("latest")
        base_fee = latest_block.get("baseFeePerGas", None)
        return {
            "gas_price_wei": gas_price_wei,
            "gas_price_gwei": round(gas_price_wei / 1e9, 2),
            "base_fee_per_gas": base_fee,
            "suggested_max_priority_fee_per_gas": self._w3.eth.max_priority_fee if hasattr(self._w3.eth, "max_priority_fee") else 1_500_000_000,
        }

    def read_contract(
        self,
        contract_address: str,
        abi: List[Dict[str, Any]],
        function_name: str,
        *args: Any,
    ) -> Any:
        addr = self.validate_and_checksum_address(contract_address)
        contract = self._w3.eth.contract(address=addr, abi=abi)
        fn = getattr(contract.functions, function_name)
        return fn(*args).call()

    # ── Agent Guardrail Simulation (Dry-Run) ──────────────────────────────────

    def simulate_transfer(
        self,
        sender: str,
        recipient: str,
        amount_token: Union[str, int],
        token_address: Optional[str] = None,
        spender: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Simulate real token transfer using eth_call.

        Validates caller, balances, and guardrails without modifying on-chain state.
        Contract reverts return isValid=False with exact revert reason.
        """
        sender_addr = self.validate_and_checksum_address(sender)
        recipient_addr = self.validate_and_checksum_address(recipient)

        # Resolve token contract
        if token_address is None:
            # Fallback to deployed AgentToken for this chain
            abi, manifest = self.network_manager.load_deployment_manifest(self.chain_id)
            token_addr = self._w3.to_checksum_address(manifest["contractAddress"])
            self.network_manager.verify_contract_bytecode(self._w3, token_addr, manifest.get("runtimeCodeHash"))
            contract = self._w3.eth.contract(address=token_addr, abi=abi)
        else:
            token_addr = self.validate_and_checksum_address(token_address)
            self.network_manager.verify_contract_bytecode(self._w3, token_addr)
            contract = self.get_erc20_contract(token_addr)

        decimals = contract.functions.decimals().call()
        units = to_token_units(amount_token, decimals)
        caller = sender_addr if spender is None else self.validate_and_checksum_address(spender)

        if spender is None:
            action = contract.functions.transfer(recipient_addr, units)
        else:
            action = contract.functions.transferFrom(sender_addr, recipient_addr, units)

        try:
            valid = bool(action.call({"from": caller}))
            reason = "Valid" if valid else "Token operation returned false"
        except ContractLogicError as exc:
            valid, reason = False, str(exc)

        return {
            "isValid": valid,
            "reason": reason,
            "sender": sender_addr,
            "recipient": recipient_addr,
            "spender": spender,
            "token_address": token_addr,
            "amount": format_token_units(units, decimals),
            "raw_amount": units,
            "chain_id": self.chain_id,
        }

    # ── Transaction Preparation ────────────────────────────────────────────────

    def prepare_native_transfer(
        self,
        from_address: str,
        to_address: str,
        amount_eth: Union[str, int, Decimal],
        priority: str = "medium",
    ) -> Dict[str, Any]:
        from_addr = self.validate_and_checksum_address(from_address)
        to_addr = self.validate_and_checksum_address(to_address)
        units = to_token_units(str(amount_eth), 18)
        nonce = self._w3.eth.get_transaction_count(from_addr, "pending")
        gas_info = self.get_gas_price()

        tx: Dict[str, Any] = {
            "from": from_addr,
            "to": to_addr,
            "value": units,
            "nonce": nonce,
            "chainId": self.chain_id,
            "gas": 21000,
        }

        if gas_info.get("base_fee_per_gas") is not None:
            base = gas_info["base_fee_per_gas"]
            priority_fee = 2_000_000_000 if priority == "high" else 1_500_000_000
            tx["maxPriorityFeePerGas"] = priority_fee
            tx["maxFeePerGas"] = base * 2 + priority_fee
            tx["type"] = "0x2"
        else:
            tx["gasPrice"] = gas_info["gas_price_wei"]

        return {
            "type": "native_transfer",
            "transaction": tx,
            "description": f"Transfer {format_token_units(units, 18)} ETH to {to_addr}",
            "amount_eth": format_token_units(units, 18),
            "raw_value": units,
        }

    def prepare_token_transfer(
        self,
        token_address: str,
        from_address: str,
        to_address: str,
        amount_token: Union[str, int],
    ) -> Dict[str, Any]:
        token_addr = self.validate_and_checksum_address(token_address)
        from_addr = self.validate_and_checksum_address(from_address)
        to_addr = self.validate_and_checksum_address(to_address)
        contract = self.get_erc20_contract(token_addr)
        decimals = contract.functions.decimals().call()
        symbol = contract.functions.symbol().call()
        units = to_token_units(amount_token, decimals)

        call_data = contract.encode_abi("transfer", args=[to_addr, units])
        nonce = self._w3.eth.get_transaction_count(from_addr, "pending")

        tx = {
            "from": from_addr,
            "to": token_addr,
            "value": 0,
            "data": call_data,
            "nonce": nonce,
            "chainId": self.chain_id,
            "gas": 65000,
            "gasPrice": self._w3.eth.gas_price,
        }

        return {
            "type": "erc20_transfer",
            "transaction": tx,
            "token_symbol": symbol,
            "token_address": token_addr,
            "amount": format_token_units(units, decimals),
            "raw_amount": units,
            "description": f"Transfer {format_token_units(units, decimals)} {symbol} to {to_addr}",
        }

    def prepare_token_approve(
        self,
        token_address: str,
        owner_address: str,
        spender_address: str,
        amount_token: Union[str, int],
    ) -> Dict[str, Any]:
        token_addr = self.validate_and_checksum_address(token_address)
        owner_addr = self.validate_and_checksum_address(owner_address)
        spender_addr = self.validate_and_checksum_address(spender_address)
        contract = self.get_erc20_contract(token_addr)
        decimals = contract.functions.decimals().call()
        symbol = contract.functions.symbol().call()
        units = to_token_units(amount_token, decimals)

        call_data = contract.encode_abi("approve", args=[spender_addr, units])
        nonce = self._w3.eth.get_transaction_count(owner_addr, "pending")

        tx = {
            "from": owner_addr,
            "to": token_addr,
            "value": 0,
            "data": call_data,
            "nonce": nonce,
            "chainId": self.chain_id,
            "gas": 50000,
            "gasPrice": self._w3.eth.gas_price,
        }

        return {
            "type": "erc20_approve",
            "transaction": tx,
            "token_symbol": symbol,
            "token_address": token_addr,
            "spender": spender_addr,
            "amount": format_token_units(units, decimals),
            "raw_amount": units,
            "description": f"Approve {spender_addr} to spend {format_token_units(units, decimals)} {symbol}",
        }

    def prepare_faucet_claim(
        self,
        token_address: str,
        recipient_address: str,
        amount_token: Union[str, int],
    ) -> Dict[str, Any]:
        token_addr = self.validate_and_checksum_address(token_address)
        recipient_addr = self.validate_and_checksum_address(recipient_address)
        abi, _ = self.network_manager.load_deployment_manifest(self.chain_id)
        contract = self._w3.eth.contract(address=token_addr, abi=abi)
        decimals = contract.functions.decimals().call()
        units = to_token_units(amount_token, decimals)

        call_data = contract.encode_abi("faucet", args=[units])

        nonce = self._w3.eth.get_transaction_count(recipient_addr, "pending")

        tx = {
            "from": recipient_addr,
            "to": token_addr,
            "value": 0,
            "data": call_data,
            "nonce": nonce,
            "chainId": self.chain_id,
            "gas": 90000,
            "gasPrice": self._w3.eth.gas_price,
        }

        return {
            "type": "faucet_claim",
            "transaction": tx,
            "recipient": recipient_addr,
            "amount": format_token_units(units, decimals),
            "raw_amount": units,
            "description": f"Claim {format_token_units(units, decimals)} AGNT from faucet for {recipient_addr}",
        }

    # ── Signing & Execution ────────────────────────────────────────────────────

    def sign_and_send_transaction(self, tx_dict: Dict[str, Any], private_key: str) -> str:
        """Sign and broadcast transaction using a private key."""
        account = Account.from_key(private_key)
        # Ensure 'from' matches key
        tx = dict(tx_dict)
        tx["from"] = account.address
        if "nonce" not in tx:
            tx["nonce"] = self._w3.eth.get_transaction_count(account.address, "pending")
        if "chainId" not in tx:
            tx["chainId"] = self.chain_id

        signed = self._w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
        return tx_hash.hex()

    def wait_for_receipt(self, tx_hash: str, timeout: int = 120, poll_latency: float = 1.0) -> Dict[str, Any]:
        """Wait for transaction receipt."""
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout, poll_latency=poll_latency)
        return dict(receipt)

    # ── Direct High-Level Execution Helpers ────────────────────────────────────

    def execute_faucet_claim(
        self,
        token_address: str,
        recipient_private_key: str,
        amount_token: Union[str, int],
    ) -> Dict[str, Any]:
        account = Account.from_key(recipient_private_key)
        prep = self.prepare_faucet_claim(token_address, account.address, amount_token)
        tx_hash = self.sign_and_send_transaction(prep["transaction"], recipient_private_key)
        receipt = self.wait_for_receipt(tx_hash)
        return {"tx_hash": tx_hash, "receipt": receipt, "status": "success" if receipt["status"] == 1 else "reverted"}

    def execute_token_transfer(
        self,
        token_address: str,
        sender_private_key: str,
        recipient_address: str,
        amount_token: Union[str, int],
    ) -> Dict[str, Any]:
        account = Account.from_key(sender_private_key)
        prep = self.prepare_token_transfer(token_address, account.address, recipient_address, amount_token)
        tx_hash = self.sign_and_send_transaction(prep["transaction"], sender_private_key)
        receipt = self.wait_for_receipt(tx_hash)
        return {"tx_hash": tx_hash, "receipt": receipt, "status": "success" if receipt["status"] == 1 else "reverted"}

    def execute_token_approve(
        self,
        token_address: str,
        owner_private_key: str,
        spender_address: str,
        amount_token: Union[str, int],
    ) -> Dict[str, Any]:
        account = Account.from_key(owner_private_key)
        prep = self.prepare_token_approve(token_address, account.address, spender_address, amount_token)
        tx_hash = self.sign_and_send_transaction(prep["transaction"], owner_private_key)
        receipt = self.wait_for_receipt(tx_hash)
        return {"tx_hash": tx_hash, "receipt": receipt, "status": "success" if receipt["status"] == 1 else "reverted"}
