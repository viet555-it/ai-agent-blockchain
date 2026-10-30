"""Bound approvals, nonce fencing and receipt reconciliation for execution."""

from __future__ import annotations

import copy
import threading
from contextlib import suppress
from typing import Any

from web3 import Web3

from backend.guardrail.policy_engine import GuardrailResult, PolicyEngine
from backend.services.transactions.models import SUPPORTED as SUPPORTED
from backend.services.transactions.models import BoundProposal, TransactionError
from backend.services.transactions.preflight import (
    ChainRules,
    LocalChainRules,
    TransactionPreflight,
)
from backend.services.transactions.preparation import TransactionPreparer, validate_proposal_request
from backend.services.transactions.serialization import digest, json_safe
from backend.services.transactions.transports import LocalTransactionTransport, TransactionTransport


class TransactionCoordinator:
    """Serializes approval/execution for one sender; preparation is delegated."""

    chain_id = 31337

    def __init__(
        self,
        blockchain: Any,
        policy: PolicyEngine,
        sender: str,
        *,
        receipt_timeout: int = 15,
        rules: ChainRules | None = None,
        transport: TransactionTransport | None = None,
    ):
        self.blockchain = blockchain
        self.policy = policy
        self.receipt_timeout = receipt_timeout
        self._lock = threading.RLock()
        self._proposals: dict[str, BoundProposal] = {}
        self._uncertain_nonce: int | None = None
        self.verifier = TransactionPreflight(
            blockchain,
            policy,
            sender,
            chain_id=self.chain_id,
            rules=rules if rules is not None else LocalChainRules(),
        )
        self.preparer = TransactionPreparer(self.verifier, policy)
        self.transport = (
            transport if transport is not None else LocalTransactionTransport(blockchain)
        )

    # Legacy identity attributes stay bound to the verifier used before approval/broadcast.
    @property
    def sender(self):
        return self.verifier.sender

    @sender.setter
    def sender(self, value):
        self.verifier.sender = value

    @property
    def contract_address(self):
        return self.verifier.contract_address

    @contract_address.setter
    def contract_address(self, value):
        self.verifier.contract_address = value

    @property
    def abi(self):
        return self.verifier.abi

    @abi.setter
    def abi(self, value):
        self.verifier.abi = value

    @property
    def runtime_hash(self):
        return self.verifier.runtime_hash

    @runtime_hash.setter
    def runtime_hash(self, value):
        self.verifier.runtime_hash = value

    @property
    def abi_hash(self):
        return self.verifier.abi_hash

    @abi_hash.setter
    def abi_hash(self, value):
        self.verifier.abi_hash = value

    def _preflight(self, tx: dict[str, Any], *, refresh_gas: bool) -> dict[str, Any]:
        return self.verifier.check(tx, refresh_gas=refresh_gas)

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
            validate_proposal_request(operation, session_id)
            if self._uncertain_nonce is not None:
                raise TransactionError(
                    "A prior broadcast has unknown outcome; reconcile it before another proposal",
                    409,
                )
            prepared = self.preparer.prepare(
                operation,
                amount=amount,
                session_id=session_id,
                recipient=recipient,
                token_address=token_address,
                actor_wallet=actor_wallet,
                preflight=self._preflight,
            )
            decision = prepared.decision
            if decision.is_allowed and decision.pending_approval:
                pending = decision.pending_approval
                self._proposals[pending.approval_id] = BoundProposal(
                    operation,
                    copy.deepcopy(pending.parameters),
                    prepared.transaction,
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
        return self.transport.broadcast(record, approval_id)

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
