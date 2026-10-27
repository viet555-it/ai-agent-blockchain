"""Integration startup must be isolated from remote endpoints and signers."""

import importlib
import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.network.network_manager import NetworkManager
from backend.runtime_profiles import RuntimeProfile, isolated_test_environment


class RuntimeProfileTests(unittest.TestCase):
    def test_import_and_factory_do_not_connect(self):
        with patch.object(
            NetworkManager, "get_healthy_provider", side_effect=AssertionError("RPC at import")
        ):
            import backend.api.server as server

            importlib.reload(server)
            server.create_app(profile="local_evm")

    def test_local_profile_rejects_external_rpc(self):
        for rpc in (
            "https://rpc.sepolia.org",
            "http://127.0.0.1.example.com:8545",
            "http://secret@localhost:8545",
            "http://localhost:8545?key=secret",
        ):
            with (
                self.subTest(rpc=rpc),
                patch.dict(os.environ, {"LOCAL_RPC_URL": rpc}),
                self.assertRaises(ValueError),
            ):
                RuntimeProfile.load("local_evm").network()

    def test_local_network_has_no_remote_fallback(self):
        with patch.dict(os.environ, {"LOCAL_RPC_URL": "http://127.0.0.1:8545"}):
            network = RuntimeProfile.load("local_evm").network()
        self.assertEqual(network.chain_id, 31337)
        self.assertEqual(network.all_rpc_urls(), ["http://127.0.0.1:8545"])

    def test_live_execution_profile_is_locked(self):
        with self.assertRaisesRegex(ValueError, "G3.2"):
            RuntimeProfile.load("sepolia_write")

    def test_unknown_profile_does_not_fall_back(self):
        with self.assertRaises(ValueError):
            RuntimeProfile.load("mainnet")

    def test_unit_requires_injection_without_rpc(self):
        from backend.api.server import create_app

        with (
            patch.object(NetworkManager, "get_healthy_provider", side_effect=AssertionError("RPC")),
            self.assertRaisesRegex(RuntimeError, "injected"),
            TestClient(create_app(profile="unit")),
        ):
            pass

    def test_injected_chain_mismatch_is_rejected(self):
        from backend.api.server import create_app

        service = MagicMock(chain_id=11155111)
        with (
            self.assertRaisesRegex(ValueError, "runtime chain"),
            TestClient(create_app(profile="unit", blockchain=service)),
        ):
            pass

    def test_signer_in_environment_cannot_enable_api_execution(self):
        from backend.api.server import create_app

        service = MagicMock(chain_id=31337)
        with (
            patch.dict(os.environ, {"SIGNER_PRIVATE_KEY": "not-a-real-key", "DRY_RUN": "false"}),
            TestClient(create_app(profile="unit", blockchain=service)) as client,
        ):
            response = client.post(
                "/api/approval/action",
                json={"approval_id": "arbitrary", "action": "APPROVE", "parameters": {}},
            )
        self.assertEqual(response.status_code, 403)
        service.sign_and_send_transaction.assert_not_called()

    def test_child_environment_blanks_secrets_before_import(self):
        with patch.dict(
            os.environ,
            {
                "SIGNER_PRIVATE_KEY": "sentinel",
                "GEMINI_API_KEY": "sentinel",
                "SEPOLIA_RPC_URL": "https://example.com/secret",
                "DRY_RUN": "false",
            },
        ):
            env = isolated_test_environment()
        self.assertEqual(env["SIGNER_PRIVATE_KEY"], "")
        self.assertEqual(env["GEMINI_API_KEY"], "")
        self.assertEqual(env["SEPOLIA_RPC_URL"], "")
        self.assertEqual(env["DRY_RUN"], "true")
        self.assertEqual(env["LLM_PROVIDER"], "fake")
