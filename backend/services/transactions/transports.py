"""Execution transports called only after coordinator approval and preflight."""

import copy
from typing import Protocol

from web3 import Web3

from backend.services.transactions.models import BoundProposal, TransactionError


class TransactionTransport(Protocol):
    def broadcast(self, record: BoundProposal, approval_id: str): ...


class LocalTransactionTransport:
    def __init__(self, blockchain):
        self.blockchain = blockchain

    def broadcast(self, record: BoundProposal, approval_id: str):
        return self.blockchain.w3.eth.send_transaction(copy.deepcopy(record.transaction))


class SepoliaTransactionTransport:
    def __init__(self, blockchain, signer, ledger, policy, transaction_fixture):
        self.blockchain = blockchain
        self.signer = signer
        self.ledger = ledger
        self.policy = policy
        self.transaction_fixture = transaction_fixture

    def broadcast(self, record: BoundProposal, approval_id: str):
        if self.transaction_fixture(record.transaction) != record.operation:
            raise TransactionError("Approval fixture changed", 409)
        tx = {key: value for key, value in record.transaction.items() if key != "from"}
        signed = self.signer.sign_transaction(tx)
        expected_hash = Web3.to_hex(Web3.keccak(signed.raw_transaction))
        self.ledger.reserve(record.operation, expected_hash, record.transaction, approval_id)
        self.policy.get_pending_approval(approval_id).tx_hash = expected_hash
        observed = self.blockchain.w3.eth.send_raw_transaction(signed.raw_transaction)
        if Web3.to_hex(observed).lower() != expected_hash.lower():
            raise TransactionError("Broadcast hash mismatch; reconcile without resending", 409)
        return observed
