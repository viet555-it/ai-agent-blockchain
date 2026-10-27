"""Real API approval and receipt checks on an isolated local deployment."""

import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from web3 import Web3

from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider
from backend.api.server import create_app
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from config.settings import Settings
from rag.retriever import SourceScope


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION_TESTS"), "Use local EVM runner")
class TransactionApiLocalTests(unittest.TestCase):
    def setUp(self):
        self.w3 = Web3(Web3.HTTPProvider(os.environ["LOCAL_TEST_RPC"]))
        self.sender, self.recipient = self.w3.eth.accounts[:2]
        root = Path(__file__).resolve().parents[2]
        artifact = json.loads(
            (root / "contracts/artifacts/src/AgentToken.sol/AgentToken.json").read_text()
        )
        self.artifact = artifact
        factory = self.w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        receipt = self.w3.eth.wait_for_transaction_receipt(
            factory.constructor(self.sender, 1000000).transact({"from": self.sender})
        )
        self.token = self.w3.eth.contract(address=receipt.contractAddress, abi=artifact["abi"])
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        target = folder / "31337"
        target.mkdir()
        (target / "AgentToken_abi.json").write_text(json.dumps(artifact["abi"]))
        (target / "deployment.json").write_text(
            json.dumps(
                {
                    "chainId": "31337",
                    "contractAddress": receipt.contractAddress,
                    "runtimeCodeHash": Web3.to_hex(
                        self.w3.keccak(self.w3.eth.get_code(receipt.contractAddress))
                    ),
                }
            )
        )
        self.enterContext(patch("backend.network.network_manager.BACKEND_ABI_DIR", folder))
        self.policy = PolicyEngine(PolicyConfig(recipient_whitelist=[self.sender, self.recipient]))

    def test_demo_setup_deploys_reuses_and_preserves_sepolia(self):
        from scripts import setup_local_demo

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        artifact = root / "contracts/artifacts/src/AgentToken.sol/AgentToken.json"
        artifact.parent.mkdir(parents=True)
        artifact.write_text(json.dumps(self.artifact))
        sepolia = root / "backend/abi/11155111/deployment.json"
        sepolia.parent.mkdir(parents=True)
        sepolia.write_text("preserve-this-fixture")
        with patch.object(setup_local_demo, "ROOT", root):
            deployed = setup_local_demo.setup(os.environ["LOCAL_TEST_RPC"])
            self.assertEqual(deployed["status"], "deployed")
            nonce = self.w3.eth.get_transaction_count(self.sender)
            reused = setup_local_demo.setup(os.environ["LOCAL_TEST_RPC"])
            self.assertEqual(reused["status"], "reused")
            self.assertEqual(deployed["contractAddress"], reused["contractAddress"])
            self.assertEqual(self.w3.eth.get_transaction_count(self.sender), nonce)
        self.assertEqual(sepolia.read_text(), "preserve-this-fixture")

    def client(self, llm=None, real_rag=False):
        retriever = (
            None
            if real_rag
            else MagicMock(scope=SourceScope("v1"), retrieve=AsyncMock(return_value=[]))
        )
        app = create_app(
            profile="local_evm",
            agent_mode="llm",
            enable_local_writes=True,
            wallet=self.sender,
            policy=self.policy,
            llm=llm or FakeLLMProvider(),
            retriever=retriever,
            agent_settings=Settings(_env_file=None, llm_provider="fake"),
        )
        return self.enterContext(TestClient(app))

    def proposal(self, client, operation="native_transfer", amount="0.001"):
        nonce = self.w3.eth.get_transaction_count(self.sender)
        response = client.post(
            "/api/transactions/propose",
            json={
                "operation": operation,
                "amount": amount,
                "recipient": self.sender if operation == "faucet_claim" else self.recipient,
                "session_id": "local-test",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.w3.eth.get_transaction_count(self.sender), nonce)
        return response.json()

    def review(self, client, pending, **changes):
        payload = {
            "approval_id": pending["approval_id"],
            "parameters": pending["parameters"],
            "session_id": "local-test",
            "action": "APPROVE",
            **changes,
        }
        return client.post("/api/approval/action", json=payload)

    def test_native_confirmation_and_idempotent_replay(self):
        client = self.client()
        before = self.w3.eth.get_balance(self.recipient)
        pending = self.proposal(client)["pending_approval"]
        result = self.review(client, pending)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "CONFIRMED")
        self.assertEqual(result.json()["receipt"]["status"], 1)
        self.assertEqual(self.w3.eth.get_balance(self.recipient) - before, 10**15)
        nonce = self.w3.eth.get_transaction_count(self.sender)
        again = self.review(client, pending).json()
        self.assertTrue(again["idempotent_replay"])
        self.assertEqual(again["tx_hash"], result.json()["tx_hash"])
        self.assertEqual(self.w3.eth.get_transaction_count(self.sender), nonce)
        url = "/api/approval/" + pending["approval_id"]
        self.assertEqual(client.get(url).status_code, 404)
        self.assertEqual(
            client.get(url, headers={"X-Session-ID": "local-test"}).json()["status"], "CONFIRMED"
        )

    def test_exact_erc20_units_and_transfer_event(self):
        client = self.client()
        pending = self.proposal(client, "erc20_transfer", "1.000000000000000001")[
            "pending_approval"
        ]
        result = self.review(client, pending).json()
        self.assertEqual(result["status"], "CONFIRMED")
        self.assertEqual(self.token.functions.balanceOf(self.recipient).call(), 10**18 + 1)
        receipt = self.w3.eth.get_transaction_receipt(result["tx_hash"])
        self.assertEqual(
            self.token.events.Transfer().process_receipt(receipt)[0]["args"]["value"], 10**18 + 1
        )

    def test_faucet_confirmation_cooldown_and_limit(self):
        client = self.client()
        before = self.token.functions.balanceOf(self.sender).call()
        pending = self.proposal(client, "faucet_claim", "10")["pending_approval"]
        self.assertEqual(self.review(client, pending).json()["status"], "CONFIRMED")
        self.assertEqual(self.token.functions.balanceOf(self.sender).call() - before, 10 * 10**18)
        self.assertFalse(self.proposal(client, "faucet_claim", "10")["is_allowed"])
        self.assertFalse(self.proposal(client, "faucet_claim", "101")["is_allowed"])
        self.assertFalse(self.proposal(client, "erc20_transfer", "501")["is_allowed"])

    def test_session_tamper_reject_and_expiry_never_send(self):
        client = self.client()
        pending = self.proposal(client)["pending_approval"]
        nonce = self.w3.eth.get_transaction_count(self.sender)
        self.assertEqual(self.review(client, pending, session_id="other").status_code, 404)
        altered = copy.deepcopy(pending["parameters"])
        altered["transaction"]["value"] = "1"
        self.assertEqual(self.review(client, pending, parameters=altered).status_code, 409)
        rejected = self.proposal(client)["pending_approval"]
        self.assertEqual(
            self.review(client, rejected, action="REJECT").json()["status"], "REJECTED"
        )
        expired = self.proposal(client)["pending_approval"]
        self.policy.get_pending_approval(expired["approval_id"]).expires_at = time.time() - 1
        self.assertEqual(self.review(client, expired).status_code, 409)
        self.assertEqual(self.w3.eth.get_transaction_count(self.sender), nonce)

    def test_chat_with_real_rag_only_proposes_until_approval(self):
        llm = FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="transfer",
                            name="transfer_erc20",
                            arguments={"to": self.recipient, "amount": "2"},
                        )
                    ]
                ),
                LLMResponse(content="Transfer completed!"),
            ]
        )
        client = self.client(llm, real_rag=True)
        nonce = self.w3.eth.get_transaction_count(self.sender)
        response = client.post(
            "/api/chat",
            json={"query": "Transfer 2 AGNT to " + self.recipient, "session_id": "local-test"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(data["requires_approval"], data)
        self.assertIsNone(data["error"])
        self.assertEqual(llm.total_calls, 1)
        self.assertEqual(data["intent"], "llm_write_proposal")
        self.assertEqual(self.w3.eth.get_transaction_count(self.sender), nonce)
        pending = data["guardrail_result"]["pending_approval"]
        self.assertNotIn(pending["approval_id"], json.dumps(llm.call_history))
        self.assertEqual(self.review(client, pending).json()["status"], "CONFIRMED")
        self.assertEqual(self.token.functions.balanceOf(self.recipient).call(), 2 * 10**18)
