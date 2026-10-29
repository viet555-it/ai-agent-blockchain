"""Contexts workflow; transaction boundaries stay at the service layer."""

from backend.db.repositories import deployments as repository
from backend.services.wallet_common import fail
from backend.wallet_values import uid


class WalletContexts:
    def __init__(self, database, blockchain, deployment_service):
        self.db = database
        self.blockchain = blockchain
        self.deployment_service = deployment_service

    def create_context(self, principal, chain_id):
        if chain_id != self.blockchain.chain_id:
            fail(409, "WRONG_NETWORK", "Switch the wallet to the runtime network.")
        deployment_id = self.deployment_service.deployment()
        context = dict(
            id=uid(), session_id=principal.session_id, deployment_id=deployment_id, generation=1
        )
        with self.db.transaction() as connection:
            repository.insert_context(connection, context)
            # Create the durable per-wallet serialization row before any authorization.
            if not repository.find_send_lock(connection, deployment_id, principal):
                repository.insert_send_lock(connection, deployment_id, principal)
        return {**context, "chain_id": chain_id, "address": principal.address}
