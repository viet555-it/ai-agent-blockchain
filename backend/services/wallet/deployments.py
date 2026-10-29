"""Deployments workflow; transaction boundaries stay at the service layer."""

from web3.exceptions import TransactionNotFound

from backend.db.repositories import deployments as repository
from backend.services.transactions.serialization import digest
from backend.services.wallet_common import fail
from backend.wallet_values import hexdata, number, uid


class WalletDeployments:
    def __init__(self, database, blockchain):
        self.db = database
        self.blockchain = blockchain

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
            found = repository.find_fingerprint(connection, fingerprint)
            repository.deactivate_other_deployments(
                connection, self.blockchain.chain_id, fingerprint
            )
            if found:
                repository.activate_deployment(connection, found)
                return found["id"]
            deployment_id = uid()
            repository.insert_deployment(
                connection, self.blockchain.chain_id, deployment_id, details, fingerprint
            )
            return deployment_id

    def deployment_unavailable(self):
        if self.blockchain.chain_id == 31337:
            message = "The saved deployment is unavailable on the current Hardhat node. Keep the node running, run .\\.venv-phase3\\Scripts\\python.exe -m scripts.setup_local_demo, then restart the API and reconnect. Keep the history database."
        else:
            message = "The saved deployment does not match the current RPC. Check the deployment manifest and contract code."
        fail(503, "DEPLOYMENT_UNAVAILABLE", message)
