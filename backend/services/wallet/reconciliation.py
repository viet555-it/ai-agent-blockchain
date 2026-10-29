"""Reconciliation workflow; transaction boundaries stay at the service layer."""

import contextlib
import time

from web3.exceptions import TransactionNotFound

from backend.db.repositories import reconciliation as repository
from backend.services.transactions.serialization import json_safe
from backend.services.wallet_common import fail, record_audit
from backend.wallet_values import hexdata, number, uid


class WalletReconciler:
    def __init__(self, database, settings, blockchain, deployment_service):
        self.db = database
        self.settings = settings
        self.blockchain = blockchain
        self.deployment_service = deployment_service

    def reconcile_batch(self):
        deployment_id = self.deployment_service.deployment()
        now = time.time()
        with self.db.transaction() as connection:
            candidates = list(repository.due_attempts(connection, deployment_id, now).scalars())
        for attempt_id in candidates:
            lease = uid()
            with self.db.transaction() as connection:
                changed = repository.claim_lease(connection, attempt_id, lease, now)
                if changed.rowcount != 1:
                    continue
                attempt = repository.find_attempt(connection, attempt_id)
                proposal = repository.find_proposal(connection, attempt)
            try:
                self._reconcile(attempt, proposal, lease)
            except Exception:
                with self.db.transaction() as connection:
                    repository.release_failed_lease(connection, attempt_id, lease)

    def _reconcile(self, attempt, proposal, lease):
        eth = self.blockchain.w3.eth
        tx_hash = attempt["tx_hash"]
        tx = None
        if tx_hash:
            with contextlib.suppress(TransactionNotFound):
                tx = eth.get_transaction(tx_hash)
        if (tx is None or tx.get("blockNumber") is None) and eth.get_transaction_count(
            proposal["transaction"]["from"], "latest"
        ) > number(proposal["transaction"]["nonce"]):
            # Bound recovery to 200 blocks; older hashes require explicit owner recovery.
            latest = eth.block_number
            start = max(number(proposal["parameters"]["prepared_block"]), latest - 199)
            found = None
            for height in range(latest, start - 1, -1):
                for candidate in eth.get_block(height, full_transactions=True)["transactions"]:
                    if str(candidate["from"]).lower() == proposal["transaction"][
                        "from"
                    ].lower() and number(candidate["nonce"]) == number(
                        proposal["transaction"]["nonce"]
                    ):
                        found = candidate
                        break
                if found is not None:
                    break
            if found is not None:
                tx, tx_hash = (found, hexdata(found["hash"]))
        if tx_hash and attempt["tx_hash"] and (tx_hash != attempt["tx_hash"]):
            if self.deployment_service.deployment() != attempt["deployment_id"]:
                return
            replacement_id = uid()
            with self.db.transaction() as connection:
                current = repository.find_leased_attempt(connection, attempt, lease)
                if not current:
                    return
                repository.insert_replacement(
                    connection, attempt, proposal, replacement_id, tx_hash
                )
                repository.mark_replaced(connection, attempt)
                repository.delete_receipt(connection, attempt)
                repository.transfer_send_lock(connection, attempt, replacement_id)
                record_audit(
                    connection,
                    proposal["wallet_id"],
                    "TRANSACTION_REPLACED",
                    proposal["id"],
                    replacement_id=replacement_id,
                )
            return
        status, verification, receipt_row = ("UNKNOWN", "UNVERIFIED", None)
        if tx is not None:
            expected = proposal["transaction"]
            matched = (
                str(tx["from"]).lower() == expected["from"].lower()
                and str(tx.get("to", "")).lower() == expected["to"].lower()
                and (number(tx["value"]) == number(expected["value"]))
                and (number(tx["nonce"]) == number(expected["nonce"]))
                and (
                    number(tx.get("chainId", self.blockchain.chain_id)) == self.blockchain.chain_id
                )
                and (
                    hexdata(tx.get("input", tx.get("data", "0x")))
                    == hexdata(expected.get("data", "0x"))
                )
                and (number(tx["gas"]) <= number(expected["gas"]))
            )
            for fee in ("gasPrice", "maxFeePerGas", "maxPriorityFeePerGas"):
                if fee in expected and number(tx.get(fee, 0)) > number(expected[fee]):
                    matched = False
            verification = "MATCHED" if matched else "MISMATCHED"
            status = "SUBMITTED"
            if tx.get("blockNumber") is not None:
                try:
                    receipt = eth.get_transaction_receipt(tx_hash)
                    block = eth.get_block(receipt["blockNumber"])
                except TransactionNotFound:
                    receipt, block = ({}, {})
                canonical = bool(receipt) and (
                    hexdata(receipt["blockHash"]) == hexdata(block["hash"])
                    and hexdata(receipt["transactionHash"]) == tx_hash.lower()
                    and (str(receipt["from"]).lower() == str(tx["from"]).lower())
                    and (str(receipt.get("to", "")).lower() == str(tx.get("to", "")).lower())
                )
                if canonical and number(receipt["status"]) in {0, 1}:
                    confirmations = eth.block_number - number(receipt["blockNumber"]) + 1
                    status = "MINED_SUCCESS" if number(receipt["status"]) else "MINED_REVERTED"
                    finalized = False
                    with contextlib.suppress(Exception):
                        finalized = number(eth.get_block("finalized")["number"]) >= number(
                            receipt["blockNumber"]
                        )
                    if finalized:
                        status = "FINALIZED"
                    receipt_row = dict(
                        id=uid(),
                        attempt_id=attempt["id"],
                        block_number=number(receipt["blockNumber"]),
                        block_hash=hexdata(receipt["blockHash"]),
                        receipt_status=number(receipt["status"]),
                        confirmations=confirmations,
                        data=json_safe(dict(receipt)),
                        finalized_at=time.time() if finalized else None,
                    )
        # Recheck the deployment after RPC work, before persisting chain evidence.
        if self.deployment_service.deployment() != attempt["deployment_id"]:
            return
        with self.db.transaction() as connection:
            current = repository.find_leased_attempt(connection, attempt, lease)
            if not current:
                return
            # A report arriving during RPC work must not have its new hash overwritten.
            if current["tx_hash"] and tx_hash and (current["tx_hash"] != tx_hash):
                fail(409, "TX_HASH", "Concurrent report needs reconciliation.")
            repository.update_observation(
                connection, attempt, current, status, tx_hash, verification
            )
            repository.update_observed_proposal(connection, proposal, tx, verification)
            if receipt_row:
                existing = repository.find_receipt(connection, attempt)
                if existing:
                    receipt_row.pop("id")
                    repository.update_receipt(connection, attempt, receipt_row)
                else:
                    repository.insert_receipt(connection, receipt_row)
            else:
                repository.delete_receipt(connection, attempt)
            if (
                status == "FINALIZED"
                and tx is not None
                and (str(tx["from"]).lower() == proposal["transaction"]["from"].lower())
                and (number(tx["nonce"]) == number(proposal["transaction"]["nonce"]))
            ):
                repository.release_send_lock(connection, attempt)
            if current["status"] != status or current["verification_status"] != verification:
                record_audit(
                    connection,
                    proposal["wallet_id"],
                    "TRANSACTION_UPDATED",
                    proposal["id"],
                    submission_id=attempt["id"],
                    status=status,
                    verification=verification,
                )
