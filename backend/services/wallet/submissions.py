"""Submissions workflow; transaction boundaries stay at the service layer."""

import secrets
import time

from backend.db.pagination import page
from backend.db.repositories import submissions as repository
from backend.db.schema_v1 import attempts
from backend.guardrail.policy_engine import PolicyEngine
from backend.services.transactions.preparation import BrowserPreparer
from backend.services.transactions.serialization import digest
from backend.services.wallet_common import fail, record_audit, require_context
from backend.wallet_values import hashed, number, token, uid


class WalletSubmissions:
    def __init__(
        self, database, settings, blockchain, policy, deployment_service, proposal_service
    ):
        self.db = database
        self.settings = settings
        self.blockchain = blockchain
        self.policy = policy
        self.deployment_service = deployment_service
        self.proposal_service = proposal_service

    def authorize(self, principal, proposal_id, context_id, generation, parameter_hash):
        if not self.settings.browser_writes:
            fail(403, "WRITES_DISABLED", "Browser-wallet transactions are disabled.")
        deployment_id = self.deployment_service.deployment()
        with self.db.transaction() as connection:
            proposal = self.proposal_service.owned(connection, principal, proposal_id)
            require_context(connection, principal, context_id, generation, deployment_id)
            if proposal["context_id"] != context_id or proposal["parameter_hash"] != parameter_hash:
                fail(409, "PAYLOAD_CHANGED", "Wallet context or proposal payload changed.")
            if proposal["status"] != "PENDING_REVIEW":
                fail(
                    409,
                    "ALREADY_REVIEWED",
                    "Proposal was already reviewed. Check its existing submission; do not send again.",
                )
            if proposal["expires_at"] <= time.time():
                fail(409, "EXPIRED", "Proposal expired. Create a new proposal.")
        if digest(self.policy.config.model_dump(mode="json")) != proposal["policy_hash"]:
            fail(409, "POLICY_CHANGED", "Policy changed. Create a new proposal.")
        if (
            PolicyEngine.compute_parameter_hash(proposal["operation"], proposal["parameters"])
            != proposal["parameter_hash"]
        ):
            fail(409, "PAYLOAD_CHANGED", "Stored proposal integrity check failed.")
        if digest(proposal["transaction"]) != proposal["parameters"]["payload_hash"]:
            fail(409, "PAYLOAD_CHANGED", "Stored transaction integrity check failed.")
        policy = self.proposal_service.policy_for(principal.address, proposal["operation"])
        preparer = BrowserPreparer(self.blockchain, policy, principal.address)
        transaction = {
            key: number(value)
            if key
            in {
                "value",
                "gas",
                "gasPrice",
                "maxFeePerGas",
                "maxPriorityFeePerGas",
                "nonce",
                "chainId",
            }
            else value
            for key, value in proposal["transaction"].items()
        }
        try:
            simulation = preparer.preflight(transaction, refresh_gas=False)
        except Exception:
            fail(
                409,
                "PREFLIGHT_CHANGED",
                "Nonce, balance, gas or chain state changed. Create a new proposal.",
            )
        if not policy.evaluate_request(
            proposal["operation"], proposal["parameters"], simulation, create_approval=False
        ).is_allowed:
            fail(409, "POLICY_CHANGED", "Proposal no longer passes policy.")
        submission_id, report_token, now = (uid(), token(), time.time())
        # Recheck context and claim the proposal/send lock in one atomic transaction.
        with self.db.transaction() as connection:
            require_context(connection, principal, context_id, generation, deployment_id)
            updated = repository.claim_pending_proposal(connection, now, proposal, proposal_id)
            if updated.rowcount != 1:
                fail(409, "ALREADY_REVIEWED", "Proposal state changed. Do not submit again.")
            repository.insert_submission(
                connection, deployment_id, now, proposal_id, report_token, submission_id
            )
            locked = repository.claim_send_lock(connection, deployment_id, principal, submission_id)
            if locked.rowcount != 1:
                fail(
                    409,
                    "WALLET_BUSY",
                    "A previous submission needs reconciliation before sending another transaction.",
                )
            repository.insert_approval(connection, now, parameter_hash, principal, proposal_id)
            record_audit(
                connection,
                principal.wallet_id,
                "SIGNATURE_REQUESTED",
                proposal_id,
                submission_id=submission_id,
            )
        return {
            "submission_id": submission_id,
            "report_token": report_token,
            "transaction": proposal["transaction"],
            "status": "AWAITING_SIGNATURE",
        }

    def report(self, submission_id, report_token, tx_hash=None, rejected=False):
        with self.db.transaction() as connection:
            attempt = repository.find_submission(connection, submission_id)
            if (
                not attempt
                or attempt["report_expires_at"] < time.time()
                or (not secrets.compare_digest(attempt["report_hash"], hashed(report_token)))
            ):
                fail(404, "NOT_FOUND", "Submission report is not authorized.")
            if tx_hash is not None:
                if not isinstance(tx_hash, str) or len(tx_hash) != 66:
                    fail(400, "TX_HASH", "Invalid transaction hash.")
                try:
                    bytes.fromhex(tx_hash[2:])
                    if not tx_hash.startswith("0x"):
                        raise ValueError()
                except ValueError:
                    fail(400, "TX_HASH", "Invalid transaction hash.")
                tx_hash = tx_hash.lower()
                if attempt["tx_hash"] and attempt["tx_hash"] != tx_hash:
                    fail(409, "TX_HASH", "Submission already has a transaction hash.")
                if attempt["status"] == "SIGNATURE_REJECTED":
                    fail(409, "SUBMISSION_STATE", "This submission was rejected.")
                repository.record_reported_hash(connection, submission_id, tx_hash)
            elif (
                rejected
                and attempt["status"] in {"AWAITING_SIGNATURE", "UNKNOWN"}
                and (not attempt["tx_hash"])
            ):
                repository.reject_signature(connection, submission_id)
                repository.reject_proposal_signature(connection, attempt)
                repository.release_send_lock(connection, submission_id)
            else:
                repository.mark_signature_unknown(connection, submission_id)
        return {"status": "RECORDED"}

    def list_transactions(self, principal, cursor=None):
        with self.db.transaction() as connection:
            query = repository.transaction_history_query(principal)
            return page(connection, query, attempts, attempts.c.created_at, cursor)

    def recover_hash(self, principal, submission_id, tx_hash):
        """Authenticated recovery after a lost hash/report capability, never permission to resend."""
        if not isinstance(tx_hash, str) or len(tx_hash) != 66 or (not tx_hash.startswith("0x")):
            fail(400, "TX_HASH", "Invalid transaction hash.")
        try:
            bytes.fromhex(tx_hash[2:])
        except ValueError:
            fail(400, "TX_HASH", "Invalid transaction hash.")
        with self.db.transaction() as connection:
            attempt = repository.find_owned_submission(connection, principal, submission_id)
            if not attempt:
                fail(404, "NOT_FOUND", "Submission not found.")
            if attempt["tx_hash"] and attempt["tx_hash"] != tx_hash.lower():
                fail(
                    409,
                    "TX_HASH",
                    "Submission already has a hash. Replacements are reconciled separately.",
                )
            repository.record_recovered_hash(connection, submission_id, tx_hash)
            record_audit(
                connection,
                principal.wallet_id,
                "HASH_RECOVERED",
                attempt["proposal_id"],
                submission_id=submission_id,
            )
        return {"status": "RECORDED"}
