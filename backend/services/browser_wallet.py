"""Public browser-wallet facade; workflows own their transactions and SQL repositories."""

from backend.services.transactions.preparation import BrowserPreparer as BrowserPreparer
from backend.services.wallet.contexts import WalletContexts
from backend.services.wallet.deployments import WalletDeployments
from backend.services.wallet.proposals import WalletProposals
from backend.services.wallet.reconciliation import WalletReconciler
from backend.services.wallet.scope import proposal_scope as proposal_scope
from backend.services.wallet.submissions import WalletSubmissions
from backend.wallet_values import hexdata as hexdata
from backend.wallet_values import number as number


class BrowserWalletService:
    def __init__(self, database, settings, blockchain, policy):
        self.db, self.settings, self.blockchain, self.policy = (
            database,
            settings,
            blockchain,
            policy,
        )
        self.deployments = WalletDeployments(database, blockchain)
        self.contexts = WalletContexts(database, blockchain, self.deployments)
        self.proposals = WalletProposals(database, settings, blockchain, policy, self.deployments)
        self.submissions = WalletSubmissions(
            database, settings, blockchain, policy, self.deployments, self.proposals
        )
        self.reconciliation = WalletReconciler(database, settings, blockchain, self.deployments)

    @property
    def contract_address(self):
        return self.deployments.contract_address

    def deployment(self):
        return self.deployments.deployment()

    def deployment_unavailable(self):
        return self.deployments.deployment_unavailable()

    def create_context(self, principal, chain_id):
        return self.contexts.create_context(principal, chain_id)

    def policy_for(self, sender, operation):
        return self.proposals.policy_for(sender, operation)

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
        return self.proposals.propose(
            operation,
            amount=amount,
            session_id=session_id,
            recipient=recipient,
            token_address=token_address,
            actor_wallet=actor_wallet,
        )

    def prepare(self, scope, operation, amount, recipient=None, token_address=None):
        return self.proposals.prepare(scope, operation, amount, recipient, token_address)

    def owned(self, connection, principal, proposal_id):
        return self.proposals.owned(connection, principal, proposal_id)

    def get(self, principal, proposal_id):
        return self.proposals.get(principal, proposal_id)

    def reject(self, principal, proposal_id, parameter_hash):
        return self.proposals.reject(principal, proposal_id, parameter_hash)

    def authorize(self, principal, proposal_id, context_id, generation, parameter_hash):
        return self.submissions.authorize(
            principal, proposal_id, context_id, generation, parameter_hash
        )

    def report(self, submission_id, report_token, tx_hash=None, rejected=False):
        return self.submissions.report(submission_id, report_token, tx_hash, rejected)

    def list_transactions(self, principal, cursor=None):
        return self.submissions.list_transactions(principal, cursor)

    def recover_hash(self, principal, submission_id, tx_hash):
        return self.submissions.recover_hash(principal, submission_id, tx_hash)

    def reconcile_batch(self):
        return self.reconciliation.reconcile_batch()

    def _reconcile(self, attempt, proposal, lease):
        return self.reconciliation._reconcile(attempt, proposal, lease)
