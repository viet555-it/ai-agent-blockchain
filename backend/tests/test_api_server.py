"""Tests for FastAPI endpoints and Agent integration."""
import unittest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from web3 import Web3
from backend.api.server import create_app
from backend.guardrail.policy_engine import PolicyEngine
from backend.network.network_manager import NetworkHealth
from backend.services.blockchain_service import BlockchainService



class ApiServerTests(unittest.TestCase):
    def setUp(self):
        self.blockchain = MagicMock(spec=BlockchainService)
        self.blockchain.chain_id = 31337
        self.blockchain.network_manager = MagicMock()
        self.blockchain.network_manager.load_deployment_manifest.return_value = (
            [], {"contractAddress": "0x" + "11" * 20})
        self.blockchain.validate_and_checksum_address.side_effect = Web3.to_checksum_address
        self.blockchain.get_token_balance.return_value = {
            "balance": "25", "symbol": "AGNT", "wallet_address": "0x" + "22" * 20,
            "token_address": "0x" + "11" * 20,
        }
        self.blockchain.get_native_balance.return_value = {"balance": "1", "symbol": "ETH"}
        self.blockchain.get_block.return_value = {"number": 123, "hash": "0x123", "transactions": []}
        self.blockchain.get_gas_price.return_value = {"gas_price_gwei": "1"}
        self.blockchain.simulate_transfer.return_value = {"isValid": True, "reason": "Valid"}
        self.policy = PolicyEngine()
        self.app = create_app(profile="unit", blockchain=self.blockchain, policy=self.policy)
        health = NetworkHealth(31337, "http://127.0.0.1:8545", True, 1.0, 123, 1)
        patcher = patch.object(self.app.state.network_manager, "check_rpc_health", return_value=health)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = self.enterContext(TestClient(self.app))

    def test_static_frontend(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('src="app.js"', response.text)

    def test_switch_outside_profile_is_blocked(self):
        response = self.client.post("/api/network/switch", json={"chain_id": 11155111})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get("/api/health").json()["chain_id"], 31337)

    def test_reject_pending_proposal(self):
        response = self.client.post("/api/chat", json={"query":
            f"Transfer 5 AGNT to {self.policy.config.recipient_whitelist[0]}"}).json()
        pending = response["guardrail_result"]["pending_approval"]
        rejected = self.client.post("/api/approval/action", json={
            "approval_id": response["approval_id"], "action": "REJECT",
            "parameters": pending["parameters"],
        })
        self.assertEqual(rejected.json()["status"], "REJECTED")
        self.blockchain.execute_token_transfer.assert_not_called()

    def test_health_endpoint(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("chain_id", data)

    def test_network_status_endpoint(self):
        res = self.client.get("/api/network/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("chain_id", data)
        self.assertIn("available_networks", data)

    def test_wallet_info_endpoint(self):
        res = self.client.get("/api/wallet/info")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("address", data)
        self.assertIn("chain_id", data)

    def test_guardrail_policies_endpoint(self):
        res = self.client.get("/api/guardrail/policies")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("recipient_whitelist", data)
        self.assertIn("max_token_transfer_limit", data)

    def test_chat_read_balance(self):
        res = self.client.post("/api/chat", json={"query": "Check balance of this wallet"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("timeline", data)
        self.assertGreater(len(data["timeline"]), 3)
        self.assertFalse(data["requires_approval"])
        self.assertIn("reply", data)

    def test_chat_faq_with_rag(self):
        res = self.client.post("/api/chat", json={"query": "What is the tokenomics and max supply of AgentToken?"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("reply", data)
        self.assertIsNotNone(data["rag_result"])
        self.assertTrue(data["rag_result"]["has_relevant_context"])

    def test_chat_write_operation_triggers_approval(self):
        whitelisted = self.policy.config.recipient_whitelist[0]
        res = self.client.post(
            "/api/chat",
            json={"query": f"Transfer 50 AGNT to {whitelisted}"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["requires_approval"])
        self.assertIsNotNone(data["approval_id"])
        self.assertEqual(data["tool_selected"], "erc20_transfer")

        approval_id = data["approval_id"]
        exact_params = data["guardrail_result"]["pending_approval"]["parameters"]

        # Execution stays disabled until G3.2, even for a valid pending proposal.
        approval_res = self.client.post(
            "/api/approval/action",
            json={
                "approval_id": approval_id,
                "action": "APPROVE",
                "parameters": exact_params,
                "reviewer_comment": "Approved by unit test",
            },
        )
        self.assertEqual(approval_res.status_code, 403)
        appr_data = approval_res.json()
        self.assertNotIn("tx_hash", appr_data)
        self.assertEqual(self.policy.get_pending_approval(approval_id).status, "PENDING")
        self.blockchain.execute_token_transfer.assert_not_called()

    def test_tampered_approval_cannot_bypass_disabled_execution(self):
        whitelisted = self.policy.config.recipient_whitelist[0]
        res = self.client.post(
            "/api/chat",
            json={"query": f"Transfer 20 AGNT to {whitelisted}"},
        )
        data = res.json()
        approval_id = data["approval_id"]
        exact_params = dict(data["guardrail_result"]["pending_approval"]["parameters"])
        exact_params["amount"] = "200"  # Tampered amount!

        tamper_res = self.client.post(
            "/api/approval/action",
            json={
                "approval_id": approval_id,
                "action": "APPROVE",
                "parameters": exact_params,
            },
        )
        self.assertEqual(tamper_res.status_code, 403)
        self.blockchain.execute_token_transfer.assert_not_called()
        self.assertEqual(self.policy.get_pending_approval(approval_id).status, "PENDING")


if __name__ == "__main__":
    unittest.main()
