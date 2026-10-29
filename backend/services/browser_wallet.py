"""Prepare browser-signed transactions and reconcile RPC evidence; never signs or sends."""

import contextlib
import contextvars
import secrets
import time

from sqlalchemy import select, update
from web3 import Web3
from web3.exceptions import TransactionNotFound

from backend.db.schema_v1 import (
    approvals,
    attempts,
    contexts,
    conversations,
    deployments,
    proposals,
    receipts,
    send_locks,
    turns,
)
from backend.guardrail.policy_engine import PolicyEngine
from backend.services.history_service import page
from backend.services.transactions.models import TransactionError
from backend.services.transactions.preparation import BrowserPreparer as BrowserPreparer
from backend.services.transactions.serialization import digest, json_safe
from backend.services.wallet_common import (
    fail,
    hashed,
    one,
    record_audit,
    require_context,
    token,
    uid,
)

proposal_scope = contextvars.ContextVar("wallet_proposal_scope", default=None)


def number(value):
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)


def hexdata(value):
    if value is None:
        return "0x"
    return value.lower() if isinstance(value, str) else Web3.to_hex(value).lower()


class BrowserWalletService:
    def __init__(self, database, settings, blockchain, policy):
        self.db, self.settings, self.blockchain, self.policy = (
            database,
            settings,
            blockchain,
            policy,
        )

    @property
    def contract_address(self):
        return self.blockchain.network_manager.load_deployment_manifest(self.blockchain.chain_id)[
            1
        ]["contractAddress"]

    def deployment(self):
        """Fingerprint the RPC instance as well as the deployment, detecting hardhat_reset."""
        abi, manifest = self.blockchain.network_manager.load_deployment_manifest(
            self.blockchain.chain_id
        )
        details = {
            "chain_id": self.blockchain.chain_id,
            "contract": manifest["contractAddress"],
            "runtime_hash": manifest.get("runtimeCodeHash"),
            "abi_hash": digest(abi),
        }
        if self.blockchain.w3.eth.chain_id != self.blockchain.chain_id:
            fail(409, "CHAIN_CHANGED", "RPC network does not match the runtime.")
        if manifest.get("transactionHash"):
            try:
                deployment_receipt = self.blockchain.w3.eth.get_transaction_receipt(
                    manifest["transactionHash"]
                )
            except TransactionNotFound:
                self.deployment_unavailable()
            if (
                number(deployment_receipt["status"]) != 1
                or str(deployment_receipt.get("contractAddress", "")).lower()
                != details["contract"].lower()
            ):
                self.deployment_unavailable()
            details["deployment_tx"] = manifest["transactionHash"]
            details["deployment_block_hash"] = hexdata(deployment_receipt["blockHash"])
        if self.blockchain.chain_id == 31337:
            metadata = self.blockchain.w3.provider.make_request("hardhat_metadata", [])
            instance = metadata.get("result", {}).get("instanceId")
            if not isinstance(instance, str) or not instance:
                fail(503, "CHAIN_IDENTITY", "Cannot identify the local Hardhat instance.")
            details["instance_id"] = instance
        details["genesis"] = hexdata(self.blockchain.w3.eth.get_block(0)["hash"])
        try:
            self.blockchain.network_manager.verify_contract_bytecode(
                self.blockchain.w3, details["contract"], details["runtime_hash"]
            )
        except ValueError:
            self.deployment_unavailable()
        fingerprint = digest(details)
        with self.db.transaction() as connection:
            found = one(
                connection, select(deployments).where(deployments.c.fingerprint == fingerprint)
            )
            connection.execute(
                update(deployments)
                .where(
                    deployments.c.chain_id == self.blockchain.chain_id,
                    deployments.c.fingerprint != fingerprint,
                )
                .values(active=False)
            )
            if found:
                connection.execute(
                    update(deployments).where(deployments.c.id == found["id"]).values(active=True)
                )
                return found["id"]
            deployment_id = uid()
            connection.execute(
                deployments.insert().values(
                    id=deployment_id,
                    chain_id=self.blockchain.chain_id,
                    fingerprint=fingerprint,
                    details=details,
                    active=True,
                    created_at=time.time(),
                )
            )
            return deployment_id

    def deployment_unavailable(self):
        if self.blockchain.chain_id == 31337:
            message = (
                "The saved deployment is unavailable on the current Hardhat node. "
                "Keep the node running, run .\\.venv-phase3\\Scripts\\python.exe "
                "-m scripts.setup_local_demo, then restart the API and reconnect. "
                "Keep the history database."
            )
        else:
            message = "The saved deployment does not match the current RPC. Check the deployment manifest and contract code."
        fail(503, "DEPLOYMENT_UNAVAILABLE", message)

    def create_context(self, principal, chain_id):
        if chain_id != self.blockchain.chain_id:
            fail(409, "WRONG_NETWORK", "Switch the wallet to the runtime network.")
        deployment_id = self.deployment()
        context = dict(
            id=uid(), session_id=principal.session_id, deployment_id=deployment_id, generation=1
        )
        with self.db.transaction() as connection:
            connection.execute(contexts.insert().values(**context))
            # A durable per-wallet serialization row; created before authorization.
            if not one(
                connection,
                select(send_locks).where(
                    send_locks.c.wallet_id == principal.wallet_id,
                    send_locks.c.deployment_id == deployment_id,
                ),
            ):
                connection.execute(
                    send_locks.insert().values(
                        id=uid(), wallet_id=principal.wallet_id, deployment_id=deployment_id
                    )
                )
        return {**context, "chain_id": chain_id, "address": principal.address}

    def policy_for(self, sender, operation):
        config = self.policy.config.model_copy(deep=True)
        # Faucet mints only to its caller; this grants no additional transfer recipients.
        if operation == "faucet_claim" and sender.lower() not in {
            item.lower() for item in config.recipient_whitelist
        }:
            config.recipient_whitelist.append(sender)
        return PolicyEngine(config)

    def propose(
        self,
        operation,
        *,
        amount,
        session_id,
        recipient=None,
        token_address=None,
        actor_wallet=None,
    ):
        """ProposalTool-compatible adapter, using trusted contextvars from history routes."""
        scope = proposal_scope.get()
        if (
            not scope
            or session_id != scope["conversation_id"]
            or actor_wallet != scope["principal"].address
        ):
            raise TransactionError("Authenticated wallet context is required", 403)
        return self.prepare(scope, operation, amount, recipient, token_address)

    def prepare(self, scope, operation, amount, recipient=None, token_address=None):
        if not self.settings.browser_writes:
            fail(403, "WRITES_DISABLED", "Browser-wallet transactions are disabled.")
        principal = scope["principal"]
        deployment_id = self.deployment()
        with self.db.transaction() as connection:
            require_context(
                connection, principal, scope["context_id"], scope["generation"], deployment_id
            )
            conversation = one(
                connection,
                select(conversations).where(
                    conversations.c.id == scope["conversation_id"],
                    conversations.c.wallet_id == principal.wallet_id,
                    conversations.c.deployment_id == deployment_id,
                    conversations.c.archived_at.is_(None),
                ),
            )
            if not conversation:
                fail(409, "CONVERSATION_CONTEXT", "Start a conversation on the current deployment.")
        preparer = BrowserPreparer(
            self.blockchain, self.policy_for(principal.address, operation), principal.address
        )
        decision = preparer.propose(
            operation,
            amount=amount,
            session_id=scope["conversation_id"],
            recipient=recipient,
            token_address=token_address,
            actor_wallet=principal.address,
        )
        if not decision.pending_approval:
            with self.db.transaction() as connection:
                record_audit(
                    connection,
                    principal.wallet_id,
                    "PROPOSAL_BLOCKED",
                    operation=operation,
                    violations=decision.violations,
                )
            return decision
        pending = decision.pending_approval
        now = time.time()
        parameters = {
            **pending.parameters,
            "context_id": scope["context_id"],
            "context_generation": scope["generation"],
            "deployment_id": deployment_id,
        }
        parameters["prepared_block"] = self.blockchain.w3.eth.block_number
        pending.parameters = parameters
        pending.parameter_hash = PolicyEngine.compute_parameter_hash(operation, parameters)
        transaction = parameters["transaction"]
        with self.db.transaction() as connection:
            require_context(
                connection, principal, scope["context_id"], scope["generation"], deployment_id
            )
            if scope.get("turn_id"):
                active_turn = one(
                    connection,
                    select(turns).where(
                        turns.c.id == scope["turn_id"], turns.c.status == "PROCESSING"
                    ),
                )
                if not active_turn:
                    fail(409, "CHAT_INTERRUPTED", "Chat turn is no longer active.")
            connection.execute(
                proposals.insert().values(
                    id=pending.approval_id,
                    wallet_id=principal.wallet_id,
                    conversation_id=scope["conversation_id"],
                    turn_id=scope.get("turn_id"),
                    context_id=scope["context_id"],
                    deployment_id=deployment_id,
                    operation=operation,
                    parameters=parameters,
                    transaction=transaction,
                    parameter_hash=pending.parameter_hash,
                    policy_hash=digest(self.policy.config.model_dump(mode="json")),
                    simulation=decision.simulation_result,
                    status="PENDING_REVIEW",
                    created_at=now,
                    expires_at=pending.expires_at,
                    version=0,
                )
            )
            record_audit(
                connection,
                principal.wallet_id,
                "PROPOSAL_CREATED",
                pending.approval_id,
                operation=operation,
            )
        return decision

    def owned(self, connection, principal, proposal_id):
        proposal = one(
            connection,
            select(proposals).where(
                proposals.c.id == proposal_id, proposals.c.wallet_id == principal.wallet_id
            ),
        )
        if not proposal:
            fail(404, "NOT_FOUND", "Proposal not found.")
        return proposal

    def get(self, principal, proposal_id):
        with self.db.transaction() as connection:
            proposal = self.owned(connection, principal, proposal_id)
            if proposal["status"] == "PENDING_REVIEW" and proposal["expires_at"] <= time.time():
                connection.execute(
                    update(proposals)
                    .where(proposals.c.id == proposal_id, proposals.c.status == "PENDING_REVIEW")
                    .values(status="EXPIRED")
                )
                proposal["status"] = "EXPIRED"
            result = {**proposal, "attempts": []}
            for row in connection.execute(
                select(attempts)
                .where(attempts.c.proposal_id == proposal_id)
                .order_by(attempts.c.created_at)
            ).mappings():
                attempt = {
                    key: value
                    for key, value in row.items()
                    if key not in {"report_hash", "report_expires_at", "lease_id", "lease_until"}
                }
                attempt["receipt"] = one(
                    connection, select(receipts).where(receipts.c.attempt_id == row["id"])
                )
                result["attempts"].append(attempt)
            return result

    def reject(self, principal, proposal_id, parameter_hash):
        with self.db.transaction() as connection:
            proposal = self.owned(connection, principal, proposal_id)
            if proposal["parameter_hash"] != parameter_hash:
                fail(409, "PAYLOAD_CHANGED", "Proposal payload does not match.")
            if proposal["status"] == "REJECTED":
                return {"status": "REJECTED"}
            changed = connection.execute(
                update(proposals)
                .where(proposals.c.id == proposal_id, proposals.c.status == "PENDING_REVIEW")
                .values(status="REJECTED", version=proposals.c.version + 1)
            )
            if changed.rowcount != 1:
                fail(409, "PROPOSAL_STATE", "Proposal can no longer be rejected before signing.")
            connection.execute(
                approvals.insert().values(
                    id=uid(),
                    proposal_id=proposal_id,
                    session_id=principal.session_id,
                    action="REJECT",
                    parameter_hash=parameter_hash,
                    created_at=time.time(),
                )
            )
            record_audit(connection, principal.wallet_id, "PROPOSAL_REJECTED", proposal_id)
        return {"status": "REJECTED"}

    def authorize(self, principal, proposal_id, context_id, generation, parameter_hash):
        if not self.settings.browser_writes:
            fail(403, "WRITES_DISABLED", "Browser-wallet transactions are disabled.")
        deployment_id = self.deployment()
        with self.db.transaction() as connection:
            proposal = self.owned(connection, principal, proposal_id)
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
        policy = self.policy_for(principal.address, proposal["operation"])
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
        submission_id, report_token, now = uid(), token(), time.time()
        with self.db.transaction() as connection:
            require_context(connection, principal, context_id, generation, deployment_id)
            updated = connection.execute(
                update(proposals)
                .where(
                    proposals.c.id == proposal_id,
                    proposals.c.status == "PENDING_REVIEW",
                    proposals.c.version == proposal["version"],
                    proposals.c.expires_at > now,
                )
                .values(status="AWAITING_SIGNATURE", version=proposals.c.version + 1)
            )
            if updated.rowcount != 1:
                fail(409, "ALREADY_REVIEWED", "Proposal state changed. Do not submit again.")
            connection.execute(
                attempts.insert().values(
                    id=submission_id,
                    proposal_id=proposal_id,
                    deployment_id=deployment_id,
                    report_hash=hashed(report_token),
                    report_expires_at=now + 86400,
                    status="AWAITING_SIGNATURE",
                    verification_status="UNVERIFIED",
                    created_at=now,
                    next_check_at=now + 15,
                    lease_until=0,
                )
            )
            locked = connection.execute(
                update(send_locks)
                .where(
                    send_locks.c.wallet_id == principal.wallet_id,
                    send_locks.c.deployment_id == deployment_id,
                    send_locks.c.attempt_id.is_(None),
                )
                .values(attempt_id=submission_id)
            )
            if locked.rowcount != 1:
                fail(
                    409,
                    "WALLET_BUSY",
                    "A previous submission needs reconciliation before sending another transaction.",
                )
            connection.execute(
                approvals.insert().values(
                    id=uid(),
                    proposal_id=proposal_id,
                    session_id=principal.session_id,
                    action="APPROVE",
                    parameter_hash=parameter_hash,
                    created_at=now,
                )
            )
            record_audit(
                connection,
                principal.wallet_id,
                "SIGNATURE_REQUESTED",
                proposal_id,
                submission_id=submission_id,
            )
        # A duplicate authorize never reissues these fields; a lost response is UNKNOWN,
        # not permission to open a second wallet send request.
        return {
            "submission_id": submission_id,
            "report_token": report_token,
            "transaction": proposal["transaction"],
            "status": "AWAITING_SIGNATURE",
        }

    def report(self, submission_id, report_token, tx_hash=None, rejected=False):
        with self.db.transaction() as connection:
            attempt = one(connection, select(attempts).where(attempts.c.id == submission_id))
            if (
                not attempt
                or attempt["report_expires_at"] < time.time()
                or not secrets.compare_digest(attempt["report_hash"], hashed(report_token))
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
                connection.execute(
                    update(attempts)
                    .where(attempts.c.id == submission_id)
                    .values(tx_hash=tx_hash, next_check_at=0)
                )
            elif (
                rejected
                and attempt["status"] in {"AWAITING_SIGNATURE", "UNKNOWN"}
                and not attempt["tx_hash"]
            ):
                connection.execute(
                    update(attempts)
                    .where(attempts.c.id == submission_id)
                    .values(status="SIGNATURE_REJECTED")
                )
                connection.execute(
                    update(proposals)
                    .where(proposals.c.id == attempt["proposal_id"])
                    .values(status="SIGNATURE_REJECTED")
                )
                connection.execute(
                    update(send_locks)
                    .where(send_locks.c.attempt_id == submission_id)
                    .values(attempt_id=None)
                )
            else:
                connection.execute(
                    update(attempts)
                    .where(
                        attempts.c.id == submission_id, attempts.c.status == "AWAITING_SIGNATURE"
                    )
                    .values(status="UNKNOWN", next_check_at=0)
                )
        return {"status": "RECORDED"}

    def list_transactions(self, principal, cursor=None):
        with self.db.transaction() as connection:
            query = (
                select(
                    attempts.c.id,
                    attempts.c.proposal_id,
                    attempts.c.tx_hash,
                    attempts.c.status,
                    attempts.c.verification_status,
                    attempts.c.created_at,
                    proposals.c.operation,
                    proposals.c.parameters,
                    proposals.c.deployment_id,
                    receipts.c.receipt_status,
                    receipts.c.confirmations,
                )
                .join(proposals)
                .outerjoin(receipts, receipts.c.attempt_id == attempts.c.id)
                .where(proposals.c.wallet_id == principal.wallet_id)
            )
            return page(connection, query, attempts, attempts.c.created_at, cursor)

    def recover_hash(self, principal, submission_id, tx_hash):
        """Authenticated recovery after a lost hash/report capability, never permission to resend."""
        if not isinstance(tx_hash, str) or len(tx_hash) != 66 or not tx_hash.startswith("0x"):
            fail(400, "TX_HASH", "Invalid transaction hash.")
        try:
            bytes.fromhex(tx_hash[2:])
        except ValueError:
            fail(400, "TX_HASH", "Invalid transaction hash.")
        with self.db.transaction() as connection:
            attempt = one(
                connection,
                select(attempts)
                .join(proposals)
                .where(
                    attempts.c.id == submission_id, proposals.c.wallet_id == principal.wallet_id
                ),
            )
            if not attempt:
                fail(404, "NOT_FOUND", "Submission not found.")
            if attempt["tx_hash"] and attempt["tx_hash"] != tx_hash.lower():
                fail(
                    409,
                    "TX_HASH",
                    "Submission already has a hash. Replacements are reconciled separately.",
                )
            connection.execute(
                update(attempts)
                .where(attempts.c.id == submission_id)
                .values(tx_hash=tx_hash.lower(), next_check_at=0, status="UNKNOWN")
            )
            record_audit(
                connection,
                principal.wallet_id,
                "HASH_RECOVERED",
                attempt["proposal_id"],
                submission_id=submission_id,
            )
        return {"status": "RECORDED"}

    def reconcile_batch(self):
        deployment_id = self.deployment()
        now = time.time()
        with self.db.transaction() as connection:
            candidates = list(
                connection.execute(
                    select(attempts.c.id)
                    .where(
                        attempts.c.deployment_id == deployment_id,
                        attempts.c.status.in_(
                            [
                                "AWAITING_SIGNATURE",
                                "UNKNOWN",
                                "SUBMITTED",
                                "MINED_SUCCESS",
                                "MINED_REVERTED",
                            ]
                        ),
                        attempts.c.next_check_at <= now,
                        attempts.c.lease_until < now,
                    )
                    .limit(20)
                ).scalars()
            )
        for attempt_id in candidates:
            lease = uid()
            with self.db.transaction() as connection:
                changed = connection.execute(
                    update(attempts)
                    .where(attempts.c.id == attempt_id, attempts.c.lease_until < now)
                    .values(lease_until=now + 120, lease_id=lease)
                )
                if changed.rowcount != 1:
                    continue
                attempt = one(connection, select(attempts).where(attempts.c.id == attempt_id))
                proposal = one(
                    connection, select(proposals).where(proposals.c.id == attempt["proposal_id"])
                )
            try:
                self._reconcile(attempt, proposal, lease)
            except Exception:
                with self.db.transaction() as connection:
                    connection.execute(
                        update(attempts)
                        .where(attempts.c.id == attempt_id, attempts.c.lease_id == lease)
                        .values(
                            lease_until=0,
                            lease_id=None,
                            next_check_at=time.time() + 30,
                            error_code="RPC_RETRY",
                        )
                    )

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
            # Bounded recovery: user can supply a hash if it is outside this window.
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
                tx, tx_hash = found, hexdata(found["hash"])
        if tx_hash and attempt["tx_hash"] and tx_hash != attempt["tx_hash"]:
            if self.deployment() != attempt["deployment_id"]:
                return
            replacement_id = uid()
            with self.db.transaction() as connection:
                current = one(
                    connection,
                    select(attempts).where(
                        attempts.c.id == attempt["id"], attempts.c.lease_id == lease
                    ),
                )
                if not current:
                    return
                connection.execute(
                    attempts.insert().values(
                        id=replacement_id,
                        proposal_id=proposal["id"],
                        deployment_id=attempt["deployment_id"],
                        report_hash=hashed(token()),
                        report_expires_at=time.time(),
                        tx_hash=tx_hash,
                        status="UNKNOWN",
                        verification_status="UNVERIFIED",
                        replaces_id=attempt["id"],
                        created_at=time.time(),
                        next_check_at=0,
                        lease_until=0,
                    )
                )
                connection.execute(
                    update(attempts)
                    .where(attempts.c.id == attempt["id"])
                    .values(
                        status="REPLACED", lease_until=0, lease_id=None, last_checked_at=time.time()
                    )
                )
                connection.execute(receipts.delete().where(receipts.c.attempt_id == attempt["id"]))
                connection.execute(
                    update(send_locks)
                    .where(send_locks.c.attempt_id == attempt["id"])
                    .values(attempt_id=replacement_id)
                )
                record_audit(
                    connection,
                    proposal["wallet_id"],
                    "TRANSACTION_REPLACED",
                    proposal["id"],
                    replacement_id=replacement_id,
                )
            return
        status, verification, receipt_row = "UNKNOWN", "UNVERIFIED", None
        if tx is not None:
            expected = proposal["transaction"]
            matched = (
                str(tx["from"]).lower() == expected["from"].lower()
                and str(tx.get("to", "")).lower() == expected["to"].lower()
                and number(tx["value"]) == number(expected["value"])
                and number(tx["nonce"]) == number(expected["nonce"])
                and number(tx.get("chainId", self.blockchain.chain_id)) == self.blockchain.chain_id
                and hexdata(tx.get("input", tx.get("data", "0x")))
                == hexdata(expected.get("data", "0x"))
                and number(tx["gas"]) <= number(expected["gas"])
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
                    receipt, block = {}, {}
                canonical = bool(receipt) and (
                    hexdata(receipt["blockHash"]) == hexdata(block["hash"])
                    and hexdata(receipt["transactionHash"]) == tx_hash.lower()
                    and str(receipt["from"]).lower() == str(tx["from"]).lower()
                    and str(receipt.get("to", "")).lower() == str(tx.get("to", "")).lower()
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
        # Recheck instance after RPC work, before persisting any chain evidence.
        if self.deployment() != attempt["deployment_id"]:
            return
        with self.db.transaction() as connection:
            current = one(
                connection,
                select(attempts).where(
                    attempts.c.id == attempt["id"], attempts.c.lease_id == lease
                ),
            )
            if not current:
                return
            # A report may have arrived while scanning. Never overwrite a new hash.
            if current["tx_hash"] and tx_hash and current["tx_hash"] != tx_hash:
                fail(409, "TX_HASH", "Concurrent report needs reconciliation.")
            connection.execute(
                update(attempts)
                .where(attempts.c.id == attempt["id"])
                .values(
                    tx_hash=tx_hash or current["tx_hash"],
                    status=status,
                    verification_status=verification,
                    last_checked_at=time.time(),
                    next_check_at=time.time() + (30 if status == "UNKNOWN" else 15),
                    lease_id=None,
                    lease_until=0,
                    error_code=None,
                )
            )
            connection.execute(
                update(proposals)
                .where(proposals.c.id == proposal["id"])
                .values(
                    status="MISMATCHED"
                    if verification == "MISMATCHED"
                    else "SUBMITTED"
                    if tx
                    else "UNKNOWN"
                )
            )
            if receipt_row:
                existing = one(
                    connection, select(receipts).where(receipts.c.attempt_id == attempt["id"])
                )
                if existing:
                    receipt_row.pop("id")
                    connection.execute(
                        update(receipts)
                        .where(receipts.c.attempt_id == attempt["id"])
                        .values(**receipt_row)
                    )
                else:
                    connection.execute(receipts.insert().values(**receipt_row))
            else:
                connection.execute(receipts.delete().where(receipts.c.attempt_id == attempt["id"]))
            if (
                status == "FINALIZED"
                and tx is not None
                and str(tx["from"]).lower() == proposal["transaction"]["from"].lower()
                and number(tx["nonce"]) == number(proposal["transaction"]["nonce"])
            ):
                connection.execute(
                    update(send_locks)
                    .where(send_locks.c.attempt_id == attempt["id"])
                    .values(attempt_id=None)
                )
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
