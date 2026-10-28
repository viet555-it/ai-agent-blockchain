"""Browser authorization/receipt flow against a disposable Hardhat deployment."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider
from backend.api.server import create_app
from backend.db.store import Database
from backend.services.blockchain_service import BlockchainService
from backend.tests import test_transactions_local_evm as legacy_local
from backend.wallet_settings import WalletSettings
from config.settings import Settings
from rag.retriever import SourceScope


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION_TESTS"), "Use the local EVM runner")
class BrowserWalletLocalTests(unittest.TestCase):
    def setUp(self):
        legacy_local.TransactionApiLocalTests.setUp(self)
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.url = "sqlite:///" + (folder / "history.db").as_posix()
        database = Database(self.url)
        database.migrate()
        database.close()
        self.blockchain = BlockchainService(w3=self.w3, chain_id=31337)
        self.llm = FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        ToolCall(id="claim", name="faucet_claim", arguments={"amount": "10"})
                    ]
                )
            ]
        )
        self.settings = WalletSettings(self.url, origin="http://testserver", browser_writes=True)
        self.app = create_app(
            profile="local_evm",
            agent_mode="llm",
            enable_local_writes=False,
            blockchain=self.blockchain,
            policy=self.policy,
            wallet_settings=self.settings,
            llm=self.llm,
            retriever=MagicMock(scope=SourceScope("v1"), retrieve=AsyncMock(return_value=[])),
            agent_settings=Settings(_env_file=None, llm_provider="fake"),
        )
        self.client = self.enterContext(TestClient(self.app))
        self.client.headers["origin"] = "http://testserver"
        challenge = self.client.post(
            "/api/auth/challenge", json={"address": self.sender, "chain_id": 31337}
        ).json()
        # The disposable node signs the login message. No environment private key is read.
        signature = self.w3.eth.sign(self.sender, text=challenge["message"])
        response = self.client.post(
            "/api/auth/verify",
            json={
                "challenge_id": challenge["challenge_id"],
                "signature": self.w3.to_hex(signature),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.client.headers["x-csrf-token"] = self.client.cookies["ati_csrf"]
        response = self.client.post("/api/wallet-contexts", json={"chain_id": 31337})
        self.assertEqual(response.status_code, 200, response.text)
        self.context = response.json()
        self.conversation = self.client.post(
            "/api/history/conversations", json={"context_id": self.context["id"], "generation": 1}
        ).json()["id"]

    def prepare(self, operation="native_transfer", amount="0.001"):
        result = self.client.post(
            "/api/wallet-proposals",
            json={
                "conversation_id": self.conversation,
                "context_id": self.context["id"],
                "generation": 1,
                "operation": operation,
                "amount": amount,
                **({"recipient": self.recipient} if operation != "faucet_claim" else {}),
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["requires_approval"], result.text)
        return result.json()["pending_approval"]

    def authorize(self, proposal):
        response = self.client.post(
            f"/api/wallet-proposals/{proposal['approval_id']}/authorize",
            json={
                "context_id": self.context["id"],
                "generation": 1,
                "parameter_hash": proposal["parameter_hash"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def send_from_test_wallet(self, submission, mutate=None):
        transaction = {
            key: int(value, 16)
            if isinstance(value, str) and value.startswith("0x") and key == "type"
            else int(value)
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
            for key, value in submission["transaction"].items()
        }
        if mutate:
            transaction.update(mutate)
        tx_hash = self.w3.to_hex(self.w3.eth.send_transaction(transaction))
        self.w3.eth.wait_for_transaction_receipt(tx_hash)
        return tx_hash

    def report(self, submission, tx_hash):
        result = self.client.post(
            f"/api/wallet-submissions/{submission['submission_id']}/report",
            json={"report_token": submission["report_token"], "tx_hash": tx_hash},
        )
        self.assertEqual(result.status_code, 200, result.text)
        self.app.state.browser_wallet.reconcile_batch()

    def test_native_transfer_and_receipt_survive_new_service(self):
        proposal = self.prepare()
        nonce_before = self.w3.eth.get_transaction_count(self.sender)
        submission = self.authorize(proposal)
        self.assertEqual(self.w3.eth.get_transaction_count(self.sender), nonce_before)
        tx_hash = self.send_from_test_wallet(submission)
        self.report(submission, tx_hash)
        result = self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").json()
        attempt = result["attempts"][0]
        self.assertEqual(attempt["verification_status"], "MATCHED", result)
        self.assertIn(attempt["status"], {"MINED_SUCCESS", "FINALIZED"}, result)
        self.assertEqual(attempt["receipt"]["receipt_status"], 1)
        self.assertEqual(attempt["tx_hash"], tx_hash)

    def test_browser_wallet_changed_value_is_not_accepted_as_proposal(self):
        proposal = self.prepare()
        submission = self.authorize(proposal)
        tx_hash = self.send_from_test_wallet(submission, {"value": 2 * 10**15})
        self.report(submission, tx_hash)
        result = self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").json()
        self.assertEqual(result["attempts"][0]["verification_status"], "MISMATCHED", result)
        self.assertEqual(result["status"], "MISMATCHED")

    def test_agent_faucet_proposal_and_erc20_transfer(self):
        response = self.client.post(
            f"/api/history/conversations/{self.conversation}/turns",
            json={
                "query": "Claim 10 AGNT from faucet",
                "context_id": self.context["id"],
                "generation": 1,
                "client_request_id": "faucet",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "COMPLETED", response.text)
        proposal = response.json()["response"]["guardrail_result"]["pending_approval"]
        submission = self.authorize(proposal)
        self.report(submission, self.send_from_test_wallet(submission))
        transfer = self.prepare("erc20_transfer", "1")
        submission = self.authorize(transfer)
        before = self.token.functions.balanceOf(self.recipient).call()
        self.report(submission, self.send_from_test_wallet(submission))
        after = self.token.functions.balanceOf(self.recipient).call()
        self.assertEqual(after - before, 10**18)
