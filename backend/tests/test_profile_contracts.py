"""Factory acceptance matrix and public contracts without starting RPC/DB/model resources."""

import csv
import itertools
import json
import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.api.server import create_app
from backend.runtime_profiles import isolated_test_environment
from backend.wallet_settings import WalletSettings

FIXTURES = Path(__file__).with_name("fixtures")
WALLET = "0x" + "11" * 20


def matrix_rows():
    with (FIXTURES / "runtime_profile_matrix.csv").open(encoding="utf-8", newline="") as stream:
        return {
            (
                row["profile"],
                row["agent_mode"],
                row["local_writes"] == "true",
                row["history"],
                row["explicit_grant"] == "true",
            )
            for row in csv.DictReader(stream)
        }


def factory(profile, mode, local_writes, history, grant):
    settings = (
        WalletSettings("sqlite:///profile-matrix.db", browser_writes=history == "write")
        if history != "off"
        else None
    )
    return create_app(
        profile=profile,
        agent_mode=mode,
        wallet=WALLET,
        enable_local_writes=local_writes,
        wallet_settings=settings,
        sepolia_execution=SimpleNamespace(sender=WALLET, recipient=WALLET) if grant else None,
    )


class ProfileContractTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch.dict(os.environ, isolated_test_environment(), clear=True))
        for target in (
            "backend.network.network_manager.NetworkManager.get_healthy_provider",
            "backend.db.store.Database.__init__",
            "rag.retriever.RAGRetriever.create",
        ):
            stack.enter_context(
                patch(target, side_effect=AssertionError("Factory opened runtime resources"))
            )

    def test_full_factory_matrix_and_http_flags(self):
        accepted = matrix_rows()
        self.assertEqual(len(accepted), 16)
        combinations = itertools.product(
            ("unit", "local_evm", "sepolia_read", "sepolia_write"),
            ("legacy", "llm"),
            (False, True),
            ("off", "read", "write"),
            (False, True),
        )
        for configuration in combinations:
            with self.subTest(configuration=configuration):
                if configuration not in accepted:
                    with self.assertRaises(ValueError):
                        factory(*configuration)
                    continue
                app = factory(*configuration)
                profile, mode, local_writes, history, _ = configuration
                # Requests without TestClient's context manager do not run lifespan.
                client = TestClient(app)
                self.addCleanup(client.close)
                health = client.get("/api/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(
                    health.json(),
                    {
                        "status": "healthy",
                        "service": "AI Agent Blockchain API",
                        "chain_id": 11155111 if profile.startswith("sepolia") else 31337,
                        "active_wallet": WALLET,
                        "agent_mode": mode,
                        "local_writes_enabled": local_writes and history == "off",
                        "wallet_history_enabled": history != "off",
                        "browser_wallet_writes": history == "write",
                    },
                )
                audits = client.get("/api/guardrail/audits")
                self.assertEqual(audits.status_code, 200 if history == "off" else 403)
                invalid = client.post("/api/chat", json={})
                self.assertEqual(invalid.status_code, 422)
                outside = 11155111 if health.json()["chain_id"] == 31337 else 31337
                switched = client.post("/api/network/switch", json={"chain_id": outside})
                self.assertEqual(switched.status_code, 400)
                if history != "off":
                    for response in (health, audits, invalid, switched):
                        self.assertEqual(response.headers["cache-control"], "no-store")
                        self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f]{32}$")

    def test_openapi_matches_pre_agent_refactor_baselines(self):
        for history, fixture in (("off", "openapi_legacy.json"), ("write", "openapi_wallet.json")):
            with self.subTest(history=history):
                app = factory("unit", "llm", False, history, False)
                expected = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
                self.assertEqual(app.openapi(), expected)

    def test_explicit_factory_flags_override_environment_defaults(self):
        with patch.dict(
            os.environ,
            {
                "PHASE3_PROFILE": "sepolia_read",
                "PHASE3_AGENT": "llm",
                "PHASE3_LOCAL_WRITES": "true",
                "WALLET_HISTORY_ENABLED": "true",
            },
        ):
            app = factory("unit", "legacy", False, "off", False)
        self.assertEqual(app.state.profile.name, "unit")
        self.assertEqual(app.state.agent_mode, "legacy")
        self.assertFalse(app.state.local_writes)
        self.assertFalse(app.state.history_enabled)

    def test_browser_write_flag_alone_does_not_enable_history(self):
        with patch.dict(
            os.environ, {"BROWSER_WALLET_WRITES": "true", "WALLET_HISTORY_ENABLED": "false"}
        ):
            app = factory("local_evm", "llm", False, "off", False)
        self.assertFalse(app.state.history_enabled)
