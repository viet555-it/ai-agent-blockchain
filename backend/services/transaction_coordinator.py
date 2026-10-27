"""Bound proposals, approval and receipt handling for an explicit local demo."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from web3 import Web3

from backend.guardrail.policy_engine import GuardrailResult, PolicyEngine
from backend.token_amounts import format_token_units, to_token_units

SUPPORTED = {"native_transfer", "erc20_transfer", "faucet_claim"}


class TransactionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return Web3.to_hex(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


@dataclass
class BoundProposal:
    operation: str
    parameters: dict[str, Any]
    transaction: dict[str, Any]
    session_id: str
    parameter_hash: str
    result: dict[str, Any] | None = None


class TransactionCoordinator:
    """Serializes one local sender; execution never receives a private key."""

    chain_id = 31337

    def __init__(
        self, blockchain: Any, policy: PolicyEngine, sender: str, *, receipt_timeout: int = 15
    ):
        self.blockchain = blockchain
        self.policy = policy
        self.sender = blockchain.validate_and_checksum_address(sender)
        self.receipt_timeout = receipt_timeout
        self._lock = threading.RLock()
        self._proposals: dict[str, BoundProposal] = {}
        self._uncertain_nonce: int | None = None
        self._validate_transport()
        self.abi, manifest = blockchain.network_manager.load_deployment_manifest(self.chain_id)
        self.contract_address = Web3.to_checksum_address(manifest["contractAddress"])
        self.runtime_hash = manifest.get("runtimeCodeHash")
        if not self.runtime_hash:
            raise TransactionError("Deployment manifest requires runtimeCodeHash")
        self.abi_hash = digest(self.abi)
        self._identity()

    def _validate_transport(self):
        blockchain = self.blockchain
        if blockchain.chain_id != self.chain_id:
            raise TransactionError("Local execution requires chain 31337", 403)
        url = urlparse(blockchain.rpc_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise TransactionError("Local execution requires a loopback HTTP RPC", 403)

    def _chain_identity(self):
        w3 = self.blockchain.w3
        if (
            self.blockchain.chain_id != self.chain_id
            or w3.eth.chain_id != self.chain_id
            or "hardhat" not in w3.client_version.lower()
        ):
            raise TransactionError("Execution requires the local Hardhat chain", 403)
        if self.sender not in [Web3.to_checksum_address(address) for address in w3.eth.accounts]:
            raise TransactionError("Configured sender must be an unlocked local account", 403)

    def _identity(self) -> None:
        self._chain_identity()
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

    def _preflight(self, tx: dict[str, Any], *, refresh_gas: bool) -> dict[str, Any]:
        self._identity()
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

    def propose(
        self,
        operation: str,
        *,
        amount: str | int,
        session_id: str,
        recipient: str | None = None,
        token_address: str | None = None,
        actor_wallet: str | None = None,
    ) -> GuardrailResult:
        with self._lock:
            if operation not in SUPPORTED:
                raise TransactionError("Unsupported write operation")
            if not session_id or len(session_id) > 128:
                raise TransactionError("A session ID is required")
            if self._uncertain_nonce is not None:
                raise TransactionError(
                    "A prior broadcast has unknown outcome; reconcile it before another proposal",
                    409,
                )
            if actor_wallet and actor_wallet.lower() != self.sender.lower():
                raise TransactionError("Active wallet must match the configured sender", 409)
            if token_address and (
                operation == "native_transfer"
                or token_address.lower() != self.contract_address.lower()
            ):
                raise TransactionError("Token contract does not match the active deployment")
            recipient = recipient or (self.sender if operation == "faucet_claim" else None)
            try:
                recipient = self.blockchain.validate_and_checksum_address(recipient)
                decimals = (
                    18
                    if operation == "native_transfer"
                    else self.blockchain.get_token_info(self.contract_address)["decimals"]
                )
                units = to_token_units(amount, decimals)
            except (TypeError, ValueError):
                raise TransactionError(
                    "Invalid recipient or amount; use an exact decimal string"
                ) from None
            if operation == "faucet_claim" and recipient != self.sender:
                raise TransactionError(
                    "Faucet mints to the sender; recipient must match the signer"
                )
            parameters = {
                "recipient": recipient,
                "amount": format_token_units(units, decimals),
                "token_symbol": "ETH" if operation == "native_transfer" else "AGNT",
                "sender": self.sender,
                "chain_id": self.chain_id,
                "session_id": session_id,
                "contract_address": self.contract_address,
                "abi_hash": self.abi_hash,
                "runtime_hash": self.runtime_hash,
                "raw_amount": str(units),
            }
            preliminary = self.policy.evaluate_request(operation, parameters, create_approval=False)
            if not preliminary.is_allowed:
                return preliminary
            self._identity()
            try:
                if operation == "native_transfer":
                    prepared = self.blockchain.prepare_native_transfer(
                        self.sender, recipient, parameters["amount"]
                    )
                elif operation == "erc20_transfer":
                    prepared = self.blockchain.prepare_token_transfer(
                        self.contract_address, self.sender, recipient, parameters["amount"]
                    )
                else:
                    prepared = self.blockchain.prepare_faucet_claim(
                        self.contract_address, self.sender, parameters["amount"]
                    )
                tx = copy.deepcopy(prepared["transaction"])
                simulation = self._preflight(tx, refresh_gas=True)
            except Exception:
                simulation = {
                    "isValid": False,
                    "reason": "Transaction simulation failed; check balance, limits, gas and faucet cooldown",
                }
                return self.policy.evaluate_request(
                    operation, parameters, simulation, create_approval=False
                )
            # JSON numbers above 2**53 are unsafe in the browser approval round trip.
            parameters["transaction"] = {k: str(v) if type(v) is int else v for k, v in tx.items()}
            parameters["payload_hash"] = digest(parameters["transaction"])
            decision = self.policy.evaluate_request(operation, parameters, simulation)
            if decision.is_allowed and decision.pending_approval:
                pending = decision.pending_approval
                self._proposals[pending.approval_id] = BoundProposal(
                    operation,
                    copy.deepcopy(pending.parameters),
                    tx,
                    session_id,
                    pending.parameter_hash,
                )
            return decision

    def _bound(self, approval_id: str, session_id: str) -> tuple[BoundProposal, Any]:
        record = self._proposals.get(approval_id)
        pending = self.policy.get_pending_approval(approval_id)
        if record is None or pending is None or record.session_id != session_id:
            raise TransactionError("Approval not found in this session", 404)
        if (
            pending.parameter_hash != record.parameter_hash
            or self.policy.compute_parameter_hash(record.operation, pending.parameters)
            != record.parameter_hash
            or digest({k: str(v) if type(v) is int else v for k, v in record.transaction.items()})
            != record.parameters["payload_hash"]
        ):
            raise TransactionError("Stored approval payload changed", 409)
        return record, pending

    def _reconcile(self, approval_id: str, record: BoundProposal, pending: Any) -> dict[str, Any]:
        if not pending.tx_hash:
            return record.result or {"status": pending.status, "approval_id": approval_id}
        try:
            receipt = self.blockchain.get_transaction_receipt(pending.tx_hash)
        except Exception:
            return record.result
        status = receipt.get("status")
        if status not in (0, 1) or receipt.get("blockNumber") is None:
            return record.result
        observed_hash = receipt.get("transactionHash")
        observed_hash = (
            observed_hash if isinstance(observed_hash, str) else Web3.to_hex(observed_hash or b"")
        )
        if (
            self.blockchain.w3.eth.chain_id != self.chain_id
            or observed_hash.lower() != pending.tx_hash.lower()
            or str(receipt.get("from", "")).lower() != record.transaction["from"].lower()
            or str(receipt.get("to", "")).lower() != record.transaction["to"].lower()
        ):
            pending.status = "UNKNOWN"
            self._uncertain_nonce = record.transaction["nonce"]
            record.result = {
                "approval_id": approval_id,
                "status": "UNKNOWN",
                "tx_hash": pending.tx_hash,
                "message": "Receipt identity mismatch; manual reconciliation required",
            }
            return copy.deepcopy(record.result)
        failed = status == 0
        self.policy.mark_executed(
            approval_id, tx_hash=pending.tx_hash, error="Transaction reverted" if failed else None
        )
        record.result = {
            "approval_id": approval_id,
            "status": "REVERTED" if failed else "CONFIRMED",
            "tx_hash": pending.tx_hash,
            "receipt": json_safe(dict(receipt)),
            "explorer_url": None,
            "message": "Transaction reverted" if failed else "Local transaction confirmed",
        }
        return copy.deepcopy(record.result)

    def review(
        self,
        approval_id: str,
        *,
        session_id: str,
        action: str,
        parameters: dict[str, Any],
        comment: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if action not in {"APPROVE", "REJECT"}:
                raise TransactionError("Unknown approval action")
            record, pending = self._bound(approval_id, session_id)
            try:
                submitted_hash = self.policy.compute_parameter_hash(record.operation, parameters)
            except (TypeError, ValueError):
                raise TransactionError(
                    "Approval parameters must be finite JSON values", 400
                ) from None
            if submitted_hash != record.parameter_hash:
                if pending.status == "PENDING":
                    pending.status = "REJECTED"
                raise TransactionError("Security Alert: approval parameters changed", 409)
            if (
                pending.status in {"EXECUTED", "SUBMITTED", "FAILED", "UNKNOWN"}
                and record.result is not None
            ):
                result = (
                    self._reconcile(approval_id, record, pending)
                    if pending.status == "SUBMITTED"
                    else copy.deepcopy(record.result)
                )
                return {**result, "idempotent_replay": True}
            ok, message, pending = self.policy.review_approval(
                approval_id, action, parameters, comment
            )
            if not ok:
                raise TransactionError(message, 409)
            if action == "REJECT":
                return {
                    "status": "REJECTED",
                    "approval_id": approval_id,
                    "message": "No transaction sent",
                }
            try:
                if (
                    record.parameters["sender"] != self.sender
                    or record.parameters["contract_address"] != self.contract_address
                    or record.parameters["abi_hash"] != self.abi_hash
                ):
                    raise TransactionError("Runtime identity changed", 409)
                simulation = self._preflight(record.transaction, refresh_gas=False)
                decision = self.policy.evaluate_request(
                    record.operation, record.parameters, simulation, create_approval=False
                )
                if not decision.is_allowed:
                    raise TransactionError(
                        "Policy changed or simulation failed; create a fresh proposal", 409
                    )
            except Exception:
                self.policy.mark_executed(
                    approval_id, error="Pre-broadcast validation failed; create a fresh proposal"
                )
                raise TransactionError(
                    "Pre-broadcast validation failed; create a fresh proposal", 409
                ) from None
            try:
                tx_hash = Web3.to_hex(self._broadcast(record, approval_id))
            except Exception:
                # Broadcast may have succeeded despite a transport error: never resubmit blindly.
                pending.status = "UNKNOWN"
                self._uncertain_nonce = record.transaction["nonce"]
                record.result = {
                    "approval_id": approval_id,
                    "status": "UNKNOWN",
                    "tx_hash": pending.tx_hash,
                    "message": "Broadcast outcome unknown; manual nonce/chain reconciliation required",
                }
                return copy.deepcopy(record.result)
            pending.tx_hash = tx_hash
            pending.status = "SUBMITTED"
            record.result = {
                "approval_id": approval_id,
                "status": "PENDING",
                "tx_hash": tx_hash,
                "message": "Broadcast; receipt not yet confirmed",
                "explorer_url": None,
            }
            with suppress(Exception):
                self.blockchain.wait_for_receipt(tx_hash, timeout=self.receipt_timeout)
            return self._reconcile(approval_id, record, pending)

    def _broadcast(self, record: BoundProposal, approval_id: str):
        return self.blockchain.w3.eth.send_transaction(copy.deepcopy(record.transaction))

    def get(self, approval_id: str, session_id: str) -> dict[str, Any]:
        with self._lock:
            record, pending = self._bound(approval_id, session_id)
            result = (
                self._reconcile(approval_id, record, pending)
                if pending.status == "SUBMITTED"
                else record.result
            )
            return {
                **pending.model_dump(),
                **(result or {}),
                "parameters": copy.deepcopy(record.parameters),
            }
