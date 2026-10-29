"""A two-fixture Sepolia grant with a durable, fail-closed fee/nonce ledger."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from eth_abi import encode
from filelock import FileLock
from web3 import Web3

from backend.services.transaction_coordinator import (
    TransactionCoordinator,
    TransactionError,
    digest,
)
from backend.services.transactions.transports import SepoliaTransactionTransport
from backend.token_amounts import to_token_units

FIXTURES = {"faucet_claim": 10 * 10**18, "erc20_transfer": 10**18}
MAX_TOTAL_FEE_WEI = 10**15  # 0.001 Sepolia ETH, approved for this two-transaction batch.


@dataclass(frozen=True)
class SepoliaExecution:
    sender: str
    recipient: str
    contract: str
    ledger_path: Path
    signer: Any = field(repr=False)

    def __post_init__(self):
        for name in ("sender", "recipient", "contract"):
            address = Web3.to_checksum_address(getattr(self, name))
            if int(address, 16) == 0:
                raise TransactionError("Zero address is not authorized")
            object.__setattr__(self, name, address)
        if self.sender == self.recipient or self.signer.address.lower() != self.sender.lower():
            raise TransactionError("Signer/recipient does not match the approved batch")

    @property
    def public_grant(self):
        return {
            "chain_id": 11155111,
            "sender": self.sender,
            "recipient": self.recipient,
            "contract": self.contract,
            "max_transactions": 2,
            "max_total_fee_wei": str(MAX_TOTAL_FEE_WEI),
            "fixtures": {key: str(value) for key, value in FIXTURES.items()},
        }


class ExecutionLedger:
    def __init__(self, config: SepoliaExecution):
        self.path = config.ledger_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock", timeout=5)
        self.grant_hash = digest(config.public_grant)

    def _load(self):
        if not self.path.exists():
            return {"grant_hash": self.grant_hash, "reservations": {}}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if state.get("grant_hash") != self.grant_hash or not isinstance(
            state.get("reservations"), dict
        ):
            raise TransactionError("Execution ledger/grant mismatch; do not reset it", 409)
        return state

    def snapshot(self):
        with self.lock:
            return self._load()

    def _save(self, state):
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(state, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def _check(self, state, operation, fee):
        entries = state["reservations"]
        if operation not in FIXTURES or operation in entries or len(entries) >= 2:
            raise TransactionError("Fixture was already consumed or is not authorized", 409)
        if any(entry["status"] != "CONFIRMED" for entry in entries.values()):
            raise TransactionError(
                "Prior broadcast must be reconciled before another transaction", 409
            )
        if (
            operation == "erc20_transfer"
            and entries.get("faucet_claim", {}).get("status") != "CONFIRMED"
        ):
            raise TransactionError("The authorized faucet must confirm before the transfer", 409)
        if (
            type(fee) is not int
            or fee <= 0
            or fee + sum(int(entry["max_fee_wei"]) for entry in entries.values())
            > MAX_TOTAL_FEE_WEI
        ):
            raise TransactionError("Approved cumulative fee cap would be exceeded", 409)

    def check(self, operation, fee):
        with self.lock:
            self._check(self._load(), operation, fee)

    def reserve(self, operation, tx_hash, tx, approval_id):
        fee = tx["gas"] * tx.get("maxFeePerGas", tx.get("gasPrice", 0))
        with self.lock:
            state = self._load()
            self._check(state, operation, fee)
            state["reservations"][operation] = {
                "status": "BROADCASTING",
                "tx_hash": tx_hash,
                "nonce": tx["nonce"],
                "max_fee_wei": str(fee),
                "approval_id": approval_id,
                "payload_hash": digest(tx),
            }
            self._save(state)  # Durable reservation before the first send_raw_transaction call.

    def settle(self, operation, tx_hash, receipt):
        with self.lock:
            state = self._load()
            entry = state["reservations"][operation]
            if entry["tx_hash"].lower() != tx_hash.lower():
                raise TransactionError("Receipt hash differs from durable reservation", 409)
            fee = receipt["gasUsed"] * receipt["effectiveGasPrice"]
            if fee > int(entry["max_fee_wei"]):
                entry["status"] = "UNKNOWN"
            else:
                entry["status"] = "CONFIRMED" if receipt["status"] == 1 else "REVERTED"
            entry.update(actual_fee_wei=str(fee), block_number=receipt["blockNumber"])
            self._save(state)
            return entry["status"]


class SepoliaChainRules:
    def __init__(self, config: SepoliaExecution):
        self.config = config

    def validate_transport(self, blockchain, chain_id):
        url = urlparse(blockchain.rpc_url)
        if blockchain.chain_id != chain_id or url.scheme != "https":
            raise TransactionError(
                "Approved Sepolia execution requires HTTPS and chain 11155111", 403
            )

    def validate_chain(self, blockchain, chain_id, sender, contract):
        if blockchain.chain_id != chain_id or blockchain.w3.eth.chain_id != chain_id:
            raise TransactionError("Sepolia chain identity changed", 403)
        if self.config.signer.address.lower() != sender.lower() or contract != self.config.contract:
            raise TransactionError("Approved signer or contract changed", 403)


class SepoliaTransactionCoordinator(TransactionCoordinator):
    chain_id = 11155111

    def __init__(self, blockchain, policy, config: SepoliaExecution, *, receipt_timeout=45):
        self.config = config
        self.ledger = ExecutionLedger(config)
        super().__init__(
            blockchain,
            policy,
            config.sender,
            receipt_timeout=receipt_timeout,
            rules=SepoliaChainRules(config),
            transport=SepoliaTransactionTransport(
                blockchain, config.signer, self.ledger, policy, self._transaction_fixture
            ),
        )

    def _calldata(self, operation):
        if operation == "faucet_claim":
            return Web3.to_hex(
                Web3.keccak(text="faucet(uint256)")[:4] + encode(["uint256"], [FIXTURES[operation]])
            )
        return Web3.to_hex(
            Web3.keccak(text="transfer(address,uint256)")[:4]
            + encode(["address", "uint256"], [self.config.recipient, FIXTURES["erc20_transfer"]])
        )

    def _transaction_fixture(self, tx):
        if tx["to"].lower() != self.config.contract.lower() or tx["value"] != 0:
            raise TransactionError("Contract/value is outside the approved batch", 403)
        for operation in FIXTURES:
            if str(tx.get("data", "")).lower() == self._calldata(operation).lower():
                return operation
        raise TransactionError("Calldata is outside the exact authorized fixtures", 403)

    def _preflight(self, tx, *, refresh_gas):
        operation = self._transaction_fixture(tx)
        simulation = super()._preflight(tx, refresh_gas=refresh_gas)
        self.ledger.check(operation, tx["gas"] * tx.get("maxFeePerGas", tx.get("gasPrice", 0)))
        return simulation

    def propose(self, operation, *, amount, session_id, recipient=None, **kwargs):
        try:
            units = to_token_units(amount, 18)
        except (TypeError, ValueError):
            raise TransactionError("An exact authorized decimal amount is required") from None
        expected = self.sender if operation == "faucet_claim" else self.config.recipient
        if (
            operation not in FIXTURES
            or units != FIXTURES[operation]
            or (recipient or expected).lower() != expected.lower()
        ):
            raise TransactionError(
                "Only faucet 10 AGNT and transfer 1 AGNT to the approved recipient are authorized",
                403,
            )
        decision = super().propose(
            operation, amount=amount, session_id=session_id, recipient=expected, **kwargs
        )
        if decision.pending_approval:
            pending = decision.pending_approval
            if (
                self._transaction_fixture(self._proposals[pending.approval_id].transaction)
                != operation
            ):
                pending.status = "REJECTED"
                raise TransactionError(
                    "Prepared calldata does not match the requested fixture", 409
                )
        return decision

    def _reconcile(self, approval_id, record, pending):
        result = super()._reconcile(approval_id, record, pending)
        if result.get("tx_hash"):
            result["explorer_url"] = "https://sepolia.etherscan.io/tx/" + result["tx_hash"]
        if result.get("status") in {"CONFIRMED", "REVERTED"}:
            status = self.ledger.settle(record.operation, pending.tx_hash, result["receipt"])
            if status == "UNKNOWN":
                pending.status = "UNKNOWN"
                self._uncertain_nonce = record.transaction["nonce"]
                result["status"] = "UNKNOWN"
                result["message"] = "Receipt fee exceeds reservation; reconcile manually"
            else:
                result["message"] = "Sepolia transaction " + status.lower()
        record.result = result
        return result
