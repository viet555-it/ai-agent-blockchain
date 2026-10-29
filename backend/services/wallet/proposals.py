"""Proposals workflow; transaction boundaries stay at the service layer."""

import time

from backend.db.repositories import proposals as repository
from backend.guardrail.policy_engine import PolicyEngine
from backend.services.transactions.models import TransactionError
from backend.services.transactions.preparation import BrowserPreparer
from backend.services.transactions.serialization import digest
from backend.services.wallet.scope import proposal_scope
from backend.services.wallet_common import fail, record_audit, require_context
from backend.wallet_errors import WalletErrorKind as ErrorKind


class WalletProposals:
    def __init__(self, database, settings, blockchain, policy, deployment_service):
        self.db = database
        self.settings = settings
        self.blockchain = blockchain
        self.policy = policy
        self.deployment_service = deployment_service

    def policy_for(self, sender, operation):
        config = self.policy.config.model_copy(deep=True)
        # Faucet mints only to its caller; this does not expand transfer recipients.
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
            fail(
                ErrorKind.PERMISSION_DENIED,
                "WRITES_DISABLED",
                "Browser-wallet transactions are disabled.",
            )
        principal = scope["principal"]
        deployment_id = self.deployment_service.deployment()
        with self.db.transaction() as connection:
            require_context(
                connection, principal, scope["context_id"], scope["generation"], deployment_id
            )
            conversation = repository.find_active_conversation(
                connection, deployment_id, principal, scope
            )
            if not conversation:
                fail(
                    ErrorKind.CONFLICT,
                    "CONVERSATION_CONTEXT",
                    "Start a conversation on the current deployment.",
                )
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
                active_turn = repository.find_processing_turn(connection, scope)
                if not active_turn:
                    fail(ErrorKind.CONFLICT, "CHAT_INTERRUPTED", "Chat turn is no longer active.")
            repository.insert_proposal(
                connection,
                decision=decision,
                deployment_id=deployment_id,
                now=now,
                operation=operation,
                parameters=parameters,
                pending=pending,
                policy_hash=digest(self.policy.config.model_dump(mode="json")),
                principal=principal,
                scope=scope,
                transaction=transaction,
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
        proposal = repository.find_owned_proposal(connection, principal, proposal_id)
        if not proposal:
            fail(ErrorKind.NOT_FOUND, "NOT_FOUND", "Proposal not found.")
        return proposal

    def get(self, principal, proposal_id):
        with self.db.transaction() as connection:
            proposal = self.owned(connection, principal, proposal_id)
            if proposal["status"] == "PENDING_REVIEW" and proposal["expires_at"] <= time.time():
                repository.expire_pending_proposal(connection, proposal_id)
                proposal["status"] = "EXPIRED"
            result = {**proposal, "attempts": []}
            for row in repository.proposal_attempts(connection, proposal_id).mappings():
                attempt = {
                    key: value
                    for key, value in row.items()
                    if key not in {"report_hash", "report_expires_at", "lease_id", "lease_until"}
                }
                attempt["receipt"] = repository.find_receipt(connection, row)
                result["attempts"].append(attempt)
            return result

    def reject(self, principal, proposal_id, parameter_hash):
        with self.db.transaction() as connection:
            proposal = self.owned(connection, principal, proposal_id)
            if proposal["parameter_hash"] != parameter_hash:
                fail(ErrorKind.CONFLICT, "PAYLOAD_CHANGED", "Proposal payload does not match.")
            if proposal["status"] == "REJECTED":
                return {"status": "REJECTED"}
            changed = repository.reject_pending_proposal(connection, proposal_id)
            if changed.rowcount != 1:
                fail(
                    ErrorKind.CONFLICT,
                    "PROPOSAL_STATE",
                    "Proposal can no longer be rejected before signing.",
                )
            repository.insert_rejection(connection, parameter_hash, principal, proposal_id)
            record_audit(connection, principal.wallet_id, "PROPOSAL_REJECTED", proposal_id)
        return {"status": "REJECTED"}
