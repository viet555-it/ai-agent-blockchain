"""Startup/read smoke through the real API lifecycle and local Hardhat RPC."""

import json
import os
import unittest

from fastapi.testclient import TestClient

from backend.api.server import create_app


@unittest.skipUnless(os.environ.get("RUN_INTEGRATION_TESTS"), "Run via the local EVM runner")
class ApiLocalEvmTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app(profile="local_evm")
        self.client = self.enterContext(TestClient(self.app))

    def test_startup_and_native_balance_use_local_chain(self):
        health = self.client.get("/api/health").json()
        self.assertEqual(health["chain_id"], 31337)
        response = self.client.post("/api/chat", json={"query": "Check ETH balance"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsNone(data["error"])
        self.assertEqual(data["tool_selected"], "get_native_balance")
        self.assertEqual(data["blockchain_result"]["chain_id"], 31337)
        expected = self.app.state.blockchain.get_native_balance(health["active_wallet"])
        self.assertEqual(data["blockchain_result"]["raw_balance"], expected["raw_balance"])

    def test_network_status_and_frontend_are_served(self):
        response = self.client.get("/api/network/status")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["chain_id"], 31337)
        self.assertTrue(all(item["chain_id"] == 31337 for item in data["available_networks"]))
        self.assertEqual(data["rpc_health"][0]["status"], "HEALTHY")
        self.assertIn('src="app.js"', self.client.get("/").text)

    def test_api_cannot_broadcast_during_baseline(self):
        response = self.client.post(
            "/api/approval/action",
            json={
                "approval_id": "arbitrary",
                "action": "APPROVE",
                "parameters": {},
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("tx_hash", response.json())

    def test_agentservice_and_real_rag_share_one_api_lifespan(self):
        from agent.llm.base import LLMResponse, ToolCall
        from agent.llm.fake import FakeLLMProvider
        from config.settings import Settings

        wallet = self.client.get("/api/health").json()["active_wallet"]
        llm = FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="native", name="get_native_balance", arguments={"address": wallet}
                        )
                    ]
                ),
                LLMResponse(content="Số dư được đọc từ RPC local."),
                LLMResponse(content="Theo source, faucet có thời gian chờ."),
                LLMResponse(content="Theo source, faucet tối đa 100 AGNT và chờ 60 giây."),
            ]
        )
        app = create_app(
            profile="local_evm",
            agent_mode="llm",
            llm=llm,
            agent_settings=Settings(_env_file=None, llm_provider="fake"),
        )
        with TestClient(app) as client:
            read = client.post(
                "/api/chat", json={"query": "Check native ETH balance", "session_id": "real-rag"}
            ).json()
            self.assertIsNone(read["error"])
            self.assertEqual(read["tool_selected"], "get_native_balance")
            self.assertEqual(read["blockchain_result"]["chain_id"], 31337)
            faq = client.post(
                "/api/chat",
                json={
                    "query": "Theo source faucet có giới hạn gì và cooldown bao lâu?",
                    "session_id": "real-rag",
                },
            ).json()
            self.assertIsNone(faq["error"])
            self.assertEqual(faq["rag_result"]["provider"], "scoped_vector_db")
            self.assertTrue(faq["rag_result"]["documents"])
            context = llm.call_history[-1]["messages"][0]["content"]
            reference_rows = [
                json.loads(line) for line in context.splitlines() if line.startswith("{")
            ]
            self.assertIn(
                faq["rag_result"]["documents"][0]["excerpt"],
                [row["content"] for row in reference_rows if "content" in row],
            )
            self.assertTrue(
                any(
                    doc["metadata"]["scope"] == "source_only"
                    for doc in faq["rag_result"]["documents"]
                )
            )
            regression_query = "Faucet giới hạn bao nhiêu AGNT mỗi lần và thời gian chờ bao lâu?"
            regression = client.post("/api/chat", json={"query": regression_query, "session_id": "real-rag"}).json()
            self.assertIsNone(regression["error"])
            self.assertEqual(regression["rag_result"]["status"], "ok")
            self.assertEqual(regression["rag_result"]["query"], regression_query)
            self.assertEqual(regression["rag_result"]["retrieval_query"], "faucet" + regression_query[6:])
            faucet_docs = [doc for doc in regression["rag_result"]["documents"]
                           if doc["source_file"] == "knowledge/contracts/faucet-and-admin-source.md"]
            excerpts = " ".join(doc["excerpt"] for doc in faucet_docs)
            self.assertIn("100", excerpts)
            self.assertIn("60", excerpts)
            self.assertTrue(all(doc["metadata"]["scope"] == "source_only" for doc in faucet_docs))
        self.assertEqual(llm.total_calls, 4)
