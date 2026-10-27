"""Real signing with a disposable fixture key; fake RPC, no external writes."""

import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import rlp
from eth_account import Account
from fastapi.testclient import TestClient
from web3 import Web3

from agent.llm.fake import FakeLLMProvider
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.services.blockchain_service import BlockchainService
from backend.services.sepolia_execution import (
    MAX_TOTAL_FEE_WEI,
    SepoliaExecution,
    SepoliaTransactionCoordinator,
)
from backend.services.transaction_coordinator import TransactionError
from config.settings import Settings
from rag.models import DeploymentScope

RECIPIENT = Web3.to_checksum_address("0x" + "22" * 20)
TOKEN = Web3.to_checksum_address("0x" + "33" * 20)


class SepoliaExecutionTests(unittest.TestCase):
    def test_live_provider_requires_durable_hash_and_never_repeats_a_send(self):
        from scripts.smoke_sepolia_write import ApprovedBatchProvider

        ledger = MagicMock()
        ledger.snapshot.return_value = {"reservations": {}}
        provider = ApprovedBatchProvider("https://fixture.invalid", ledger)
        raw = "0xdead"
        expected_hash = Web3.to_hex(Web3.keccak(bytes.fromhex("dead")))
        with patch.object(
            Web3.HTTPProvider, "make_request", return_value={"result": expected_hash}
        ) as transport:
            with self.assertRaises(RuntimeError):
                provider.make_request("eth_sendRawTransaction", [raw])
            ledger.snapshot.return_value = {
                "reservations": {
                    "faucet_claim": {"tx_hash": expected_hash, "status": "BROADCASTING"}
                }
            }
            provider.make_request("eth_sendRawTransaction", [raw])
            with self.assertRaises(RuntimeError):
                provider.make_request("eth_sendRawTransaction", [raw])
            with self.assertRaises(RuntimeError):
                provider.make_request("eth_sendTransaction", [{}])
            transport.assert_called_once()

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.signer = Account.from_key(b"\x11" * 32)  # Public test fixture, never .env.
        self.sender = self.signer.address
        self.config = SepoliaExecution(
            self.sender, RECIPIENT, TOKEN, self.root / "ledger.json", self.signer
        )
        self.policy = PolicyEngine(PolicyConfig(recipient_whitelist=[self.sender, RECIPIENT]))
        self.service = MagicMock(spec=BlockchainService)
        self.service.chain_id = 11155111
        self.service.rpc_url = "https://fixture.invalid"
        self.service.validate_and_checksum_address.side_effect = Web3.to_checksum_address
        self.service.network_manager = MagicMock()
        self.service.network_manager.load_deployment_manifest.return_value = (
            [],
            {"contractAddress": TOKEN, "runtimeCodeHash": "test-hash"},
        )
        self.service.network_manager.verify_contract_bytecode.return_value = True
        self.service.get_token_info.return_value = {"decimals": 18}
        self.w3 = self.service.w3 = MagicMock()
        self.w3.eth.chain_id = 11155111
        self.nonce = 0
        self.price = 10**9
        self.receipt = None
        self.w3.eth.get_transaction_count.side_effect = lambda *args: self.nonce
        self.w3.eth.get_balance.return_value = 10**22
        self.w3.eth.estimate_gas.return_value = 50000
        self.w3.eth.send_raw_transaction.side_effect = self.send
        self.service.prepare_faucet_claim.side_effect = lambda *args: {
            "transaction": self.tx("faucet_claim")
        }
        self.service.prepare_token_transfer.side_effect = lambda *args: {
            "transaction": self.tx("erc20_transfer")
        }
        self.service.get_transaction_receipt.side_effect = lambda _: copy.deepcopy(self.receipt)
        self.coordinator = SepoliaTransactionCoordinator(self.service, self.policy, self.config)

    def tx(self, operation):
        return {
            "from": self.sender,
            "to": TOKEN,
            "value": 0,
            "data": self.coordinator._calldata(operation),
            "nonce": self.nonce,
            "chainId": 11155111,
            "gas": 90000,
            "gasPrice": self.price,
        }

    def send(self, raw):
        self.assertEqual(Account.recover_transaction(raw), self.sender)
        self.assertIn(
            int.from_bytes(rlp.decode(raw)[6], "big"), [2 * 11155111 + 35, 2 * 11155111 + 36]
        )
        tx_hash = Web3.keccak(raw)
        self.nonce += 1
        self.receipt = {
            "transactionHash": tx_hash,
            "from": self.sender,
            "to": TOKEN,
            "status": 1,
            "blockNumber": self.nonce,
            "gasUsed": 50000,
            "effectiveGasPrice": self.price,
        }
        return tx_hash

    def proposal(self, operation="faucet_claim"):
        result = self.coordinator.propose(
            operation, amount="10" if operation == "faucet_claim" else "1", session_id="session"
        )
        self.assertTrue(result.requires_approval, result)
        return result.pending_approval

    def approve(self, pending):
        return self.coordinator.review(
            pending.approval_id,
            session_id="session",
            action="APPROVE",
            parameters=pending.parameters,
        )

    def tearDown(self):
        self.w3.eth.send_transaction.assert_not_called()
        self.w3.eth.account.sign_transaction.assert_not_called()

    def test_two_exact_fixtures_sign_for_sepolia_and_confirm_with_durable_cap(self):
        faucet = self.proposal()
        self.w3.eth.send_raw_transaction.assert_not_called()
        self.assertEqual(self.approve(faucet)["status"], "CONFIRMED")
        transfer = self.proposal("erc20_transfer")
        result = self.approve(transfer)
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertIn("sepolia.etherscan.io/tx/", result["explorer_url"])
        state = self.coordinator.ledger.snapshot()["reservations"]
        self.assertEqual(len(state), 2)
        self.assertTrue(all(row["status"] == "CONFIRMED" for row in state.values()))
        self.assertLessEqual(
            sum(int(row["max_fee_wei"]) for row in state.values()), MAX_TOTAL_FEE_WEI
        )
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 2)
        self.assertTrue(self.approve(transfer)["idempotent_replay"])
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 2)

    def test_wrong_signer_contract_chain_and_transport_fail_closed(self):
        with self.assertRaises(TransactionError):
            SepoliaExecution(RECIPIENT, self.sender, TOKEN, self.root / "other.json", self.signer)
        self.w3.eth.chain_id = 1
        with self.assertRaises(TransactionError):
            self.proposal()
        self.w3.eth.chain_id = 11155111
        self.service.rpc_url = "http://127.0.0.1:8545"
        with self.assertRaises(TransactionError):
            SepoliaTransactionCoordinator(self.service, self.policy, self.config)
        self.service.rpc_url = "https://fixture.invalid"
        self.service.network_manager.load_deployment_manifest.return_value[1]["contractAddress"] = (
            RECIPIENT
        )
        with self.assertRaises(TransactionError):
            SepoliaTransactionCoordinator(self.service, self.policy, self.config)
        self.w3.eth.send_raw_transaction.assert_not_called()

    def test_other_amount_recipient_and_native_transfer_are_not_authorized(self):
        for operation, amount, recipient in [
            ("faucet_claim", "100", self.sender),
            ("erc20_transfer", "2", RECIPIENT),
            ("faucet_claim", "10", RECIPIENT),
            ("erc20_transfer", "1", self.sender),
            ("native_transfer", "0.000001", RECIPIENT),
        ]:
            with (
                self.subTest(operation=operation, amount=amount, recipient=recipient),
                self.assertRaises(TransactionError),
            ):
                self.coordinator.propose(
                    operation, amount=amount, recipient=recipient, session_id="session"
                )
        self.w3.eth.send_raw_transaction.assert_not_called()

    def test_semantically_wrong_calldata_cannot_get_approval(self):
        bad = self.tx("faucet_claim")
        bad["data"] = "0xdeadbeef"
        self.service.prepare_faucet_claim.side_effect = lambda *args: {"transaction": bad}
        result = self.coordinator.propose("faucet_claim", amount="10", session_id="session")
        self.assertFalse(result.is_allowed)
        self.w3.eth.send_raw_transaction.assert_not_called()

    def test_fee_cap_is_enforced_before_approval_and_signature(self):
        self.price = MAX_TOTAL_FEE_WEI
        result = self.coordinator.propose("faucet_claim", amount="10", session_id="session")
        self.assertFalse(result.is_allowed)
        self.assertFalse(self.config.ledger_path.exists())
        self.w3.eth.send_raw_transaction.assert_not_called()

    def test_estimation_is_not_capped_by_the_prepared_gas_template(self):
        def estimate(call):
            self.assertNotIn("gas", call)
            return 157897

        self.w3.eth.estimate_gas.side_effect = estimate
        pending = self.proposal()
        self.assertEqual(pending.parameters["transaction"]["gas"], "189477")
        self.w3.eth.send_raw_transaction.assert_not_called()
        self.assertEqual(self.approve(pending)["status"], "CONFIRMED")

    def test_transfer_cannot_precede_faucet(self):
        result = self.coordinator.propose("erc20_transfer", amount="1", session_id="session")
        self.assertFalse(result.is_allowed)
        self.w3.eth.send_raw_transaction.assert_not_called()

    def test_cumulative_cap_cannot_be_reset_by_a_second_fixture(self):
        self.approve(self.proposal())
        self.price = 11 * 10**9  # Individually under cap; exceeds it with the first reservation.
        result = self.coordinator.propose("erc20_transfer", amount="1", session_id="session")
        self.assertFalse(result.is_allowed)
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_reverted_faucet_is_not_success_and_cannot_be_retried(self):
        original = self.send

        def reverted(raw):
            tx_hash = original(raw)
            self.receipt["status"] = 0
            return tx_hash

        self.w3.eth.send_raw_transaction.side_effect = reverted
        self.assertEqual(self.approve(self.proposal())["status"], "REVERTED")
        self.assertEqual(
            self.coordinator.ledger.snapshot()["reservations"]["faucet_claim"]["status"], "REVERTED"
        )
        self.assertFalse(
            self.coordinator.propose("erc20_transfer", amount="1", session_id="session").is_allowed
        )
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_api_uses_the_same_bound_approval_and_does_not_expose_signer_key(self):
        import hashlib

        from backend.api import server

        abi_text = "[]"
        folder = self.root / "backend/abi/11155111"
        folder.mkdir(parents=True)
        (folder / "AgentToken_abi.json").write_text(abi_text)
        manifest = {
            "chainId": "11155111",
            "contractAddress": TOKEN,
            "deployer": self.sender,
            "runtimeCodeHash": "test-hash",
        }
        (folder / "deployment.json").write_text(json.dumps(manifest))
        retriever = MagicMock(
            scope=DeploymentScope(
                11155111, TOKEN, "sha256:" + hashlib.sha256(abi_text.encode()).hexdigest(), "test"
            ),
            retrieve=AsyncMock(return_value=[]),
        )
        with (
            patch.object(server, "REPO_ROOT", self.root),
            patch("backend.network.network_manager.BACKEND_ABI_DIR", folder.parent),
        ):
            app = server.create_app(
                profile="sepolia_write",
                agent_mode="llm",
                enable_local_writes=False,
                sepolia_execution=self.config,
                blockchain=self.service,
                wallet=self.sender,
                retriever=retriever,
                llm=FakeLLMProvider(),
                agent_settings=Settings(_env_file=None, llm_provider="fake"),
            )
            with TestClient(app) as client:
                proposal = client.post(
                    "/api/transactions/propose",
                    json={"operation": "faucet_claim", "amount": "10", "session_id": "api"},
                )
                self.assertEqual(proposal.status_code, 200, proposal.text)
                pending = proposal.json()["pending_approval"]
                self.w3.eth.send_raw_transaction.assert_not_called()
                result = client.post(
                    "/api/approval/action",
                    json={
                        "approval_id": pending["approval_id"],
                        "parameters": pending["parameters"],
                        "action": "APPROVE",
                        "session_id": "api",
                    },
                )
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["status"], "CONFIRMED")
                self.assertNotIn(
                    self.signer.key.hex(),
                    result.text
                    + proposal.text
                    + repr(self.config)
                    + self.config.ledger_path.read_text(),
                )
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_restart_never_reissues_consumed_fixture(self):
        self.approve(self.proposal())
        fresh = SepoliaTransactionCoordinator(
            self.service, PolicyEngine(self.policy.config), self.config
        )
        result = fresh.propose("faucet_claim", amount="10", session_id="new-session")
        self.assertFalse(result.is_allowed)
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_resume_accepts_only_same_grant_and_matching_confirmed_receipts(self):
        from scripts.smoke_sepolia_write import resumable_rows

        result = self.approve(self.proposal())
        state = self.coordinator.ledger.snapshot()
        previous = {
            "grant": self.config.public_grant,
            "cases": [
                {"operation": "faucet_claim", "status": "CONFIRMED", "tx_hash": result["tx_hash"]}
            ],
        }
        self.assertEqual(set(resumable_rows(self.config, state, previous)), {"faucet_claim"})
        with self.assertRaises(RuntimeError):
            resumable_rows(self.config, state, {**previous, "grant": {}})
        bad = copy.deepcopy(previous)
        bad["cases"][0]["tx_hash"] = "0xwrong"
        with self.assertRaises(RuntimeError):
            resumable_rows(self.config, state, bad)
        state["reservations"]["faucet_claim"]["status"] = "BROADCASTING"
        with self.assertRaises(RuntimeError):
            resumable_rows(self.config, state, previous)
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_unknown_broadcast_is_reserved_before_rpc_and_blocks_restart(self):
        pending = self.proposal()

        def uncertain(raw):
            self.assertEqual(len(self.coordinator.ledger.snapshot()["reservations"]), 1)
            raise TimeoutError("https://fixture.invalid/secret")

        self.w3.eth.send_raw_transaction.side_effect = uncertain
        result = self.approve(pending)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertTrue(result["tx_hash"])
        self.assertNotIn("secret", json.dumps(result))
        fresh = SepoliaTransactionCoordinator(
            self.service, PolicyEngine(self.policy.config), self.config
        )
        for operation, amount in [("faucet_claim", "10"), ("erc20_transfer", "1")]:
            self.assertFalse(
                fresh.propose(operation, amount=amount, session_id="restart").is_allowed
            )
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_pending_receipt_polls_without_resending(self):
        pending = self.proposal()
        self.service.wait_for_receipt.side_effect = TimeoutError()
        self.service.get_transaction_receipt.side_effect = TimeoutError()
        self.assertEqual(self.approve(pending)["status"], "PENDING")
        self.service.get_transaction_receipt.side_effect = lambda _: copy.deepcopy(self.receipt)
        self.assertEqual(
            self.coordinator.get(pending.approval_id, "session")["status"], "CONFIRMED"
        )
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_concurrent_approval_sends_once(self):
        pending = self.proposal()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.approve(pending), range(2)))
        self.assertEqual([row["status"] for row in results], ["CONFIRMED", "CONFIRMED"])
        self.assertEqual(self.w3.eth.send_raw_transaction.call_count, 1)

    def test_tampering_or_corrupt_ledger_cannot_send(self):
        pending = self.proposal()
        changed = copy.deepcopy(pending.parameters)
        changed["transaction"]["chainId"] = "1"
        with self.assertRaises(TransactionError):
            self.coordinator.review(
                pending.approval_id, session_id="session", action="APPROVE", parameters=changed
            )
        self.config.ledger_path.write_text('{"grant_hash":"changed","reservations":{}}')
        self.assertFalse(
            self.coordinator.propose("faucet_claim", amount="10", session_id="session").is_allowed
        )
        self.w3.eth.send_raw_transaction.assert_not_called()
