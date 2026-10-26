"""Tests for FastAPI endpoints and Agent integration."""
import unittest
from fastapi.testclient import TestClient
from backend.api.server import app, policy_engine

client = TestClient(app)


class ApiServerTests(unittest.TestCase):
    def test_health_endpoint(self):
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("chain_id", data)

    def test_network_status_endpoint(self):
        res = client.get("/api/network/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("chain_id", data)
        self.assertIn("available_networks", data)

    def test_wallet_info_endpoint(self):
        res = client.get("/api/wallet/info")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("address", data)
        self.assertIn("chain_id", data)

    def test_guardrail_policies_endpoint(self):
        res = client.get("/api/guardrail/policies")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("recipient_whitelist", data)
        self.assertIn("max_token_transfer_limit", data)

    def test_chat_read_balance(self):
        res = client.post("/api/chat", json={"query": "Check balance of this wallet"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("timeline", data)
        self.assertGreater(len(data["timeline"]), 3)
        self.assertFalse(data["requires_approval"])
        self.assertIn("reply", data)

    def test_chat_faq_with_rag(self):
        res = client.post("/api/chat", json={"query": "What is the tokenomics and max supply of AgentToken?"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("reply", data)
        self.assertIsNotNone(data["rag_result"])
        self.assertTrue(data["rag_result"]["has_relevant_context"])

    def test_chat_write_operation_triggers_approval(self):
        whitelisted = policy_engine.config.recipient_whitelist[0]
        res = client.post(
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

        # Test approving the transaction
        approval_res = client.post(
            "/api/approval/action",
            json={
                "approval_id": approval_id,
                "action": "APPROVE",
                "parameters": exact_params,
                "reviewer_comment": "Approved by unit test",
            },
        )
        self.assertEqual(approval_res.status_code, 200)
        appr_data = approval_res.json()
        self.assertEqual(appr_data["status"], "EXECUTED")
        self.assertIn("tx_hash", appr_data)

    def test_approval_tamper_rejection(self):
        whitelisted = policy_engine.config.recipient_whitelist[0]
        res = client.post(
            "/api/chat",
            json={"query": f"Transfer 20 AGNT to {whitelisted}"},
        )
        data = res.json()
        approval_id = data["approval_id"]
        exact_params = dict(data["guardrail_result"]["pending_approval"]["parameters"])
        exact_params["amount"] = "200"  # Tampered amount!

        tamper_res = client.post(
            "/api/approval/action",
            json={
                "approval_id": approval_id,
                "action": "APPROVE",
                "parameters": exact_params,
            },
        )
        self.assertEqual(tamper_res.status_code, 400)
        self.assertIn("Security Alert", tamper_res.json()["detail"])


if __name__ == "__main__":
    unittest.main()
