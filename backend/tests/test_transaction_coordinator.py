"""Approval/execution boundary tests; deterministic fake RPC, no keys/network."""

import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from unittest.mock import MagicMock

from web3 import Web3

from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.services.blockchain_service import BlockchainService
from backend.services.transaction_coordinator import TransactionCoordinator, TransactionError
from backend.token_amounts import to_token_units

SENDER = Web3.to_checksum_address("0x" + "11" * 20)
RECIPIENT = Web3.to_checksum_address("0x" + "22" * 20)
TOKEN = Web3.to_checksum_address("0x" + "33" * 20)
HASH = b"\xaa" * 32


class TransactionCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.service = MagicMock(spec=BlockchainService)
        self.service.chain_id = 31337
        self.service.rpc_url = "http://127.0.0.1:8545"
        self.service.validate_and_checksum_address.side_effect = Web3.to_checksum_address
        self.service.network_manager = MagicMock()
        self.abi = [{"type": "function", "name": "faucet"}]
        self.manifest = {"chainId": "31337", "contractAddress": TOKEN, "runtimeCodeHash": "0xhash"}
        self.service.network_manager.load_deployment_manifest.return_value = (
            self.abi,
            self.manifest,
        )
        self.service.network_manager.verify_contract_bytecode.return_value = True
        self.service.get_token_info.return_value = {"decimals": 18}
        self.w3 = self.service.w3 = MagicMock()
        self.w3.client_version = "HardhatNetwork/test"
        self.w3.eth.chain_id = 31337
        self.w3.eth.accounts = [SENDER, RECIPIENT]
        self.nonce = 0
        self.w3.eth.get_transaction_count.side_effect = lambda *a: self.nonce
        self.w3.eth.get_balance.return_value = 10**24
        self.w3.eth.estimate_gas.return_value = 21000
        self.service.prepare_native_transfer.side_effect = lambda sender, recipient, amount: {
            "transaction": {
                "from": sender,
                "to": recipient,
                "value": to_token_units(amount, 18),
                "nonce": self.nonce,
                "chainId": 31337,
                "gas": 21000,
                "gasPrice": 1,
            }
        }
        self.service.prepare_token_transfer.side_effect = lambda token, sender, recipient, amount: {
            "transaction": {
                "from": sender,
                "to": token,
                "value": 0,
                "data": "0xabcdef",
                "nonce": self.nonce,
                "chainId": 31337,
                "gas": 65000,
                "gasPrice": 1,
            }
        }
        self.service.prepare_faucet_claim.side_effect = lambda token, sender, amount: {
            "transaction": {
                "from": sender,
                "to": token,
                "value": 0,
                "data": "0xfaucet",
                "nonce": self.nonce,
                "chainId": 31337,
                "gas": 90000,
                "gasPrice": 1,
            }
        }
        self.w3.eth.send_transaction.side_effect = self.send
        self.receipt = {
            "transactionHash": HASH,
            "status": 1,
            "blockNumber": 1,
            "from": SENDER,
            "to": RECIPIENT,
            "gasUsed": 21000,
        }
        self.service.get_transaction_receipt.side_effect = lambda _: copy.deepcopy(self.receipt)
        self.policy = PolicyEngine(PolicyConfig(recipient_whitelist=[SENDER, RECIPIENT]))
        self.coordinator = TransactionCoordinator(self.service, self.policy, SENDER)

    def send(self, tx):
        self.nonce += 1
        return HASH

    def proposal(self, **kwargs):
        return self.coordinator.propose(
            "native_transfer", amount="0.1", recipient=RECIPIENT, session_id="session-a", **kwargs
        ).pending_approval

    def approve(self, pending, **kwargs):
        return self.coordinator.review(
            pending.approval_id,
            session_id="session-a",
            action="APPROVE",
            parameters=copy.deepcopy(pending.parameters),
            **kwargs,
        )

    def test_prepare_is_bound_exact_and_does_not_send(self):
        p = self.proposal()
        self.assertEqual(p.parameters["transaction"]["value"], "100000000000000000")
        self.assertEqual(p.parameters["chain_id"], 31337)
        self.assertEqual(p.parameters["sender"], SENDER)
        self.assertEqual(p.parameters["session_id"], "session-a")
        self.assertIn("payload_hash", p.parameters)
        self.w3.eth.call.assert_called_once()
        self.w3.eth.send_transaction.assert_not_called()

    def test_confirmed_and_idempotent_replay_send_once(self):
        p = self.proposal()
        first = self.approve(p)
        second = self.approve(p)
        self.assertEqual(first["status"], "CONFIRMED")
        self.assertEqual(first["tx_hash"], "0x" + HASH.hex())
        self.assertEqual(first["receipt"]["status"], 1)
        self.assertTrue(second["idempotent_replay"])
        self.w3.eth.send_transaction.assert_called_once()

    def test_concurrent_double_click_sends_once(self):
        p = self.proposal()
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: self.approve(p), range(2)))
        self.assertTrue(all(r["status"] == "CONFIRMED" for r in responses))
        self.w3.eth.send_transaction.assert_called_once()

    def test_tampered_fields_and_extra_fields_are_rejected(self):
        mutations = [
            ("amount", "0.2"),
            ("sender", RECIPIENT),
            ("chain_id", 11155111),
            ("contract_address", RECIPIENT),
            ("abi_hash", "other"),
            ("runtime_hash", "other"),
            ("session_id", "other"),
            ("_ignored", "must-be-bound"),
            ("chain_id", "31337"),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                p = self.proposal()
                params = copy.deepcopy(p.parameters)
                params[field] = value
                with self.assertRaises(TransactionError):
                    self.coordinator.review(
                        p.approval_id, session_id="session-a", action="APPROVE", parameters=params
                    )
                self.assertEqual(p.status, "REJECTED")
        self.w3.eth.send_transaction.assert_not_called()

    def test_nested_payload_tamper_and_server_mutation_are_rejected(self):
        p = self.proposal()
        params = copy.deepcopy(p.parameters)
        params["transaction"]["value"] = "200000000000000000"
        with self.assertRaises(TransactionError):
            self.coordinator.review(
                p.approval_id, session_id="session-a", action="APPROVE", parameters=params
            )
        p2 = self.proposal()
        self.coordinator._proposals[p2.approval_id].transaction["to"] = TOKEN
        with self.assertRaises(TransactionError):
            self.approve(p2)
        self.w3.eth.send_transaction.assert_not_called()

    def test_cross_session_cannot_read_or_approve(self):
        p = self.proposal()
        for action in (
            lambda: self.coordinator.get(p.approval_id, "other"),
            lambda: self.coordinator.review(
                p.approval_id, session_id="other", action="APPROVE", parameters=p.parameters
            ),
        ):
            with self.assertRaises(TransactionError) as caught:
                action()
            self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.approve(p)["status"], "CONFIRMED")

    def test_reject_and_expiry_cannot_be_approved(self):
        p = self.proposal()
        result = self.coordinator.review(
            p.approval_id, session_id="session-a", action="REJECT", parameters=p.parameters
        )
        self.assertEqual(result["status"], "REJECTED")
        with self.assertRaises(TransactionError):
            self.approve(p)
        p2 = self.proposal()
        p2.expires_at = 0
        with self.assertRaises(TransactionError):
            self.approve(p2)
        self.assertEqual(p2.status, "EXPIRED")
        self.w3.eth.send_transaction.assert_not_called()

    def test_invalid_action_does_not_consume_approval(self):
        p = self.proposal()
        with self.assertRaises(TransactionError):
            self.coordinator.review(
                p.approval_id, session_id="session-a", action="UNKNOWN", parameters=p.parameters
            )
        self.assertEqual(p.status, "PENDING")

    def test_nonce_change_requires_fresh_approval(self):
        first, stale = self.proposal(), self.proposal()
        self.approve(first)
        with self.assertRaises(TransactionError):
            self.approve(stale)
        self.assertEqual(stale.status, "FAILED")
        self.w3.eth.send_transaction.assert_called_once()

    def test_policy_change_and_runtime_change_block_send(self):
        p = self.proposal()
        self.policy.config.max_native_transfer_limit = Decimal("0.01")
        with self.assertRaises(TransactionError):
            self.approve(p)
        self.policy.config.max_native_transfer_limit = Decimal("0.5")
        p2 = self.proposal()
        self.w3.eth.chain_id = 11155111
        with self.assertRaises(TransactionError):
            self.approve(p2)
        self.w3.eth.send_transaction.assert_not_called()

    def test_sender_and_deployment_changes_block_send(self):
        p = self.proposal()
        self.coordinator.sender = RECIPIENT
        with self.assertRaises(TransactionError):
            self.approve(p)
        self.coordinator.sender = SENDER
        p2 = self.proposal()
        self.manifest["runtimeCodeHash"] = "changed"
        with self.assertRaises(TransactionError):
            self.approve(p2)
        self.w3.eth.send_transaction.assert_not_called()

    def test_reverted_receipt_is_not_success(self):
        p = self.proposal()
        self.receipt["status"] = 0
        result = self.approve(p)
        self.assertEqual(result["status"], "REVERTED")
        self.assertEqual(p.status, "FAILED")
        self.assertEqual(self.approve(p)["status"], "REVERTED")
        self.w3.eth.send_transaction.assert_called_once()

    def test_receipt_timeout_is_pending_and_reconciles_without_resending(self):
        p = self.proposal()
        self.service.wait_for_receipt.side_effect = TimeoutError()
        self.service.get_transaction_receipt.side_effect = None
        self.service.get_transaction_receipt.return_value = {"status": "pending"}
        self.assertEqual(self.approve(p)["status"], "PENDING")
        self.assertEqual(self.approve(p)["status"], "PENDING")
        self.service.get_transaction_receipt.return_value = self.receipt
        self.assertEqual(self.coordinator.get(p.approval_id, "session-a")["status"], "CONFIRMED")
        self.w3.eth.send_transaction.assert_called_once()

    def test_ambiguous_broadcast_is_unknown_and_fences_new_proposals(self):
        p = self.proposal()
        self.w3.eth.send_transaction.side_effect = ConnectionError()
        self.assertEqual(self.approve(p)["status"], "UNKNOWN")
        self.assertEqual(self.approve(p)["status"], "UNKNOWN")
        with self.assertRaises(TransactionError):
            self.proposal()
        self.w3.eth.send_transaction.assert_called_once()

    def test_mismatched_receipt_is_unknown(self):
        p = self.proposal()
        self.receipt["transactionHash"] = b"\xbb" * 32
        self.assertEqual(self.approve(p)["status"], "UNKNOWN")

    def test_bad_amounts_unsupported_operations_and_faucet_recipient(self):
        for amount in (True, 1.1, "NaN", "Infinity", "-1", "1e3", "0.0000000000000000001"):
            with self.subTest(amount=amount), self.assertRaises(TransactionError):
                self.coordinator.propose(
                    "native_transfer", amount=amount, recipient=RECIPIENT, session_id="session-a"
                )
        with self.assertRaises(TransactionError):
            self.coordinator.propose(
                "erc20_approve", amount="1", recipient=RECIPIENT, session_id="session-a"
            )
        with self.assertRaises(TransactionError):
            self.coordinator.propose(
                "faucet_claim", amount="1", recipient=RECIPIENT, session_id="session-a"
            )
        self.w3.eth.send_transaction.assert_not_called()

    def test_limits_zero_address_simulation_and_gas_fail_closed(self):
        for amount, recipient in (("0", RECIPIENT), ("0.6", RECIPIENT), ("0.1", "0x" + "00" * 20)):
            with self.subTest(amount=amount, recipient=recipient):
                self.assertFalse(
                    self.coordinator.propose(
                        "native_transfer",
                        amount=amount,
                        recipient=recipient,
                        session_id="session-a",
                    ).is_allowed
                )
        self.w3.eth.call.side_effect = RuntimeError("revert")
        self.assertFalse(
            self.coordinator.propose(
                "native_transfer", amount="0.1", recipient=RECIPIENT, session_id="session-a"
            ).is_allowed
        )
        self.w3.eth.call.side_effect = None
        self.w3.eth.get_balance.return_value = 0
        self.assertFalse(
            self.coordinator.propose(
                "native_transfer", amount="0.1", recipient=RECIPIENT, session_id="session-a"
            ).is_allowed
        )
        self.w3.eth.send_transaction.assert_not_called()

    def test_disabled_approval_or_whitelist_and_remote_network_are_rejected(self):
        for field in ("require_human_approval_for_writes", "enforce_whitelist"):
            setattr(self.policy.config, field, False)
            with self.subTest(field=field), self.assertRaises(TransactionError):
                TransactionCoordinator(self.service, self.policy, SENDER)
            setattr(self.policy.config, field, True)
        self.service.chain_id = 11155111
        with self.assertRaises(TransactionError):
            TransactionCoordinator(self.service, self.policy, SENDER)

    def test_status_response_is_a_copy(self):
        p = self.proposal()
        response = self.coordinator.get(p.approval_id, "session-a")
        response["parameters"]["amount"] = "999"
        self.assertEqual(p.parameters["amount"], "0.1")

    def test_nested_web3_receipt_logs_are_json_safe(self):
        import json

        from web3.datastructures import AttributeDict

        p = self.proposal()
        self.receipt["logs"] = [AttributeDict({"topics": [HASH], "data": b"\xdd\xff"})]
        result = self.approve(p)
        self.assertEqual(result["receipt"]["logs"][0]["data"], "0xddff")
        json.dumps(result, allow_nan=False)

    def test_nonfinite_approval_parameter_is_rejected_without_send(self):
        p = self.proposal()
        parameters = copy.deepcopy(p.parameters)
        parameters["amount"] = float("nan")
        with self.assertRaises(TransactionError):
            self.coordinator.review(
                p.approval_id, session_id="session-a", action="APPROVE", parameters=parameters
            )
        self.w3.eth.send_transaction.assert_not_called()

    def test_unknown_policy_operations_and_missing_fields_are_blocked(self):
        self.assertFalse(self.policy.evaluate_request("send_everything", {}).is_allowed)
        self.assertFalse(self.policy.evaluate_request("native_transfer", {}).is_allowed)
        self.assertFalse(
            self.policy.evaluate_request(
                "native_transfer", {"recipient": RECIPIENT, "amount": "0.1"}, {}
            ).is_allowed
        )
