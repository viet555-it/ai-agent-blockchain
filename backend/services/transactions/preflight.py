"""Chain/deployment identity and simulation checks for unsigned transactions."""

from typing import Any, Protocol
from urllib.parse import urlparse

from web3 import Web3

from backend.guardrail.policy_engine import PolicyEngine
from backend.services.transactions.models import TransactionError
from backend.services.transactions.serialization import digest


class ChainRules(Protocol):
    def validate_transport(self, blockchain: Any, chain_id: int) -> None: ...
    def validate_chain(
        self, blockchain: Any, chain_id: int, sender: str, contract: str
    ) -> None: ...


class LocalChainRules:
    def validate_transport(self, blockchain, chain_id):
        if blockchain.chain_id != chain_id:
            raise TransactionError("Local execution requires chain 31337", 403)
        url = urlparse(blockchain.rpc_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise TransactionError("Local execution requires a loopback HTTP RPC", 403)

    def validate_chain(self, blockchain, chain_id, sender, contract):
        w3 = blockchain.w3
        if (
            blockchain.chain_id != chain_id
            or w3.eth.chain_id != chain_id
            or "hardhat" not in w3.client_version.lower()
        ):
            raise TransactionError("Execution requires the local Hardhat chain", 403)
        if sender not in [Web3.to_checksum_address(address) for address in w3.eth.accounts]:
            raise TransactionError("Configured sender must be an unlocked local account", 403)


class BrowserChainRules:
    def validate_transport(self, blockchain, chain_id):
        if chain_id not in {31337, 11155111}:
            raise TransactionError("Browser execution supports local Hardhat and Sepolia only", 403)
        if chain_id == 31337:
            LocalChainRules().validate_transport(blockchain, chain_id)

    def validate_chain(self, blockchain, chain_id, sender, contract):
        if blockchain.w3.eth.chain_id != chain_id:
            raise TransactionError("RPC chain changed", 409)


class TransactionPreflight:
    def __init__(
        self, blockchain, policy: PolicyEngine, sender: str, *, chain_id: int, rules: ChainRules
    ):
        self.blockchain = blockchain
        self.policy = policy
        self.sender = blockchain.validate_and_checksum_address(sender)
        self.chain_id = chain_id
        self.rules = rules
        rules.validate_transport(blockchain, chain_id)
        self.abi, manifest = blockchain.network_manager.load_deployment_manifest(chain_id)
        self.contract_address = Web3.to_checksum_address(manifest["contractAddress"])
        self.runtime_hash = manifest.get("runtimeCodeHash")
        if not self.runtime_hash:
            raise TransactionError("Deployment manifest requires runtimeCodeHash")
        self.abi_hash = digest(self.abi)
        self.check_identity()

    def check_identity(self) -> None:
        self.rules.validate_chain(
            self.blockchain, self.chain_id, self.sender, self.contract_address
        )
        w3 = self.blockchain.w3
        abi, manifest = self.blockchain.network_manager.load_deployment_manifest(self.chain_id)
        if (
            manifest["contractAddress"].lower() != self.contract_address.lower()
            or manifest.get("runtimeCodeHash") != self.runtime_hash
            or digest(abi) != self.abi_hash
        ):
            raise TransactionError("Deployment/ABI changed; create a fresh proposal", 409)
        if (
            self.blockchain.network_manager.verify_contract_bytecode(
                w3, self.contract_address, self.runtime_hash
            )
            is not True
        ):
            raise TransactionError("Contract bytecode verification failed", 403)
        if (
            not self.policy.config.require_human_approval_for_writes
            or not self.policy.config.enforce_whitelist
        ):
            raise TransactionError(
                "Human approval and recipient whitelist must remain enabled", 403
            )

    def check(self, tx: dict[str, Any], *, refresh_gas: bool) -> dict[str, Any]:
        self.check_identity()
        w3 = self.blockchain.w3
        if tx["chainId"] != self.chain_id or tx["from"] != self.sender:
            raise TransactionError("Transaction chain/sender does not match runtime", 409)
        if w3.eth.get_transaction_count(self.sender, "pending") != tx["nonce"]:
            raise TransactionError("Nonce changed; create a fresh proposal", 409)
        call = {k: v for k, v in tx.items() if k not in {"nonce", "chainId", "type"}}
        # Template gas limits must not cap the estimator before we can size them.
        estimate = w3.eth.estimate_gas({key: value for key, value in call.items() if key != "gas"})
        if refresh_gas:
            tx["gas"] = max(tx["gas"], (estimate * 120 + 99) // 100)
            call["gas"] = tx["gas"]
        elif estimate > tx["gas"]:
            raise TransactionError("Gas requirements changed; create a fresh proposal", 409)
        fee_cap = tx.get("maxFeePerGas", tx.get("gasPrice", 0))
        if w3.eth.get_balance(self.sender) < tx["value"] + tx["gas"] * fee_cap:
            raise TransactionError("Insufficient native balance for value and worst-case gas")
        w3.eth.call(call)
        return {
            "isValid": True,
            "reason": "eth_call and gas/balance checks passed",
            "gas_estimate": estimate,
            "gas_limit": tx["gas"],
            "max_fee_wei": str(tx["gas"] * fee_cap),
        }
