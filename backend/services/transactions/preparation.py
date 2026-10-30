"""Build unsigned proposals; this module has no approval-review or broadcast path."""

import copy
from collections.abc import Callable

from backend.guardrail.policy_engine import PolicyEngine
from backend.services.transactions.models import SUPPORTED, PreparedProposal, TransactionError
from backend.services.transactions.preflight import BrowserChainRules, TransactionPreflight
from backend.services.transactions.serialization import digest
from backend.token_amounts import format_token_units, to_token_units


def validate_proposal_request(operation: str, session_id: str) -> None:
    if operation not in SUPPORTED:
        raise TransactionError("Unsupported write operation")
    if not session_id or len(session_id) > 128:
        raise TransactionError("A session ID is required")


class TransactionPreparer:
    def __init__(self, verifier: TransactionPreflight, policy: PolicyEngine):
        self.verifier = verifier
        self.policy = policy

    def prepare(
        self,
        operation: str,
        *,
        amount: str | int,
        session_id: str,
        recipient: str | None = None,
        token_address: str | None = None,
        actor_wallet: str | None = None,
        preflight: Callable | None = None,
    ) -> PreparedProposal:
        validate_proposal_request(operation, session_id)
        check = preflight if preflight is not None else self.verifier.check
        if actor_wallet and actor_wallet.lower() != self.verifier.sender.lower():
            raise TransactionError("Active wallet must match the configured sender", 409)
        if token_address and (
            operation == "native_transfer"
            or token_address.lower() != self.verifier.contract_address.lower()
        ):
            raise TransactionError("Token contract does not match the active deployment")
        recipient = recipient or (self.verifier.sender if operation == "faucet_claim" else None)
        try:
            recipient = self.verifier.blockchain.validate_and_checksum_address(recipient)
            decimals = (
                18
                if operation == "native_transfer"
                else self.verifier.blockchain.get_token_info(self.verifier.contract_address)[
                    "decimals"
                ]
            )
            units = to_token_units(amount, decimals)
        except (TypeError, ValueError):
            raise TransactionError(
                "Invalid recipient or amount; use an exact decimal string"
            ) from None
        if operation == "faucet_claim" and recipient != self.verifier.sender:
            raise TransactionError("Faucet mints to the sender; recipient must match the signer")
        parameters = {
            "recipient": recipient,
            "amount": format_token_units(units, decimals),
            "token_symbol": "ETH" if operation == "native_transfer" else "AGNT",
            "sender": self.verifier.sender,
            "chain_id": self.verifier.chain_id,
            "session_id": session_id,
            "contract_address": self.verifier.contract_address,
            "abi_hash": self.verifier.abi_hash,
            "runtime_hash": self.verifier.runtime_hash,
            "raw_amount": str(units),
        }
        preliminary = self.policy.evaluate_request(operation, parameters, create_approval=False)
        if not preliminary.is_allowed:
            return PreparedProposal(preliminary)
        self.verifier.check_identity()
        try:
            if operation == "native_transfer":
                prepared = self.verifier.blockchain.prepare_native_transfer(
                    self.verifier.sender, recipient, parameters["amount"]
                )
            elif operation == "erc20_transfer":
                prepared = self.verifier.blockchain.prepare_token_transfer(
                    self.verifier.contract_address,
                    self.verifier.sender,
                    recipient,
                    parameters["amount"],
                )
            else:
                prepared = self.verifier.blockchain.prepare_faucet_claim(
                    self.verifier.contract_address, self.verifier.sender, parameters["amount"]
                )
            tx = copy.deepcopy(prepared["transaction"])
            simulation = check(tx, refresh_gas=True)
        except Exception:
            simulation = {
                "isValid": False,
                "reason": "Transaction simulation failed; check balance, limits, gas and faucet cooldown",
            }
            return PreparedProposal(
                self.policy.evaluate_request(
                    operation, parameters, simulation, create_approval=False
                )
            )
        # JSON numbers above 2**53 are unsafe in the browser approval round trip.
        parameters["transaction"] = {k: str(v) if type(v) is int else v for k, v in tx.items()}
        parameters["payload_hash"] = digest(parameters["transaction"])
        decision = self.policy.evaluate_request(operation, parameters, simulation)
        return PreparedProposal(decision, tx)


class BrowserPreparer:
    """Browser proposal adapter with no signing, review or execution transport."""

    def __init__(self, blockchain, policy, sender):
        self.verifier = TransactionPreflight(
            blockchain, policy, sender, chain_id=blockchain.chain_id, rules=BrowserChainRules()
        )
        self.preparer = TransactionPreparer(self.verifier, policy)

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
        return self.preparer.prepare(
            operation,
            amount=amount,
            session_id=session_id,
            recipient=recipient,
            token_address=token_address,
            actor_wallet=actor_wallet,
        ).decision

    def preflight(self, transaction, *, refresh_gas):
        return self.verifier.check(transaction, refresh_gas=refresh_gas)
