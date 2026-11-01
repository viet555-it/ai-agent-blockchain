"""Automated tests for Guardrail Configuration Management, 'Thử chặn' (Test-Block),
Security Authorization, and Proposal Re-evaluation upon policy changes.
"""

import tempfile
import time
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from sqlalchemy import select
from web3 import Web3

from agent.llm.base import LLMResponse
from agent.llm.fake import FakeLLMProvider
from backend.api.server import create_app
from backend.db.repositories import guardrail_configs as gc_repo
from backend.db.schema_limits_v2 import entries as limit_entries
from backend.db.schema_v1 import proposals, sessions
from backend.db.store import Database
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.services.blockchain_service import BlockchainService
from backend.wallet_settings import WalletSettings
from config.settings import Settings
from rag.retriever import SourceScope

ORIGIN = "http://testserver"


class GuardrailManagementTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.url = "sqlite:///" + (self.folder / "test_guardrail.db").as_posix()
        database = Database(self.url)
        database.migrate()
        database.close()

        self.a = Account.create()
        self.b = Account.create()
        self.recipient_1 = Account.create().address
        self.recipient_2 = Account.create().address

        self.chain = MagicMock(spec=BlockchainService)
        self.chain.chain_id = 31337
        self.chain.rpc_url = "http://127.0.0.1:8545"
        self.chain.validate_and_checksum_address.side_effect = Web3.to_checksum_address
        self.chain.w3 = MagicMock()
        self.chain.w3.eth.chain_id = 31337
        self.chain.w3.eth.block_number = 100
        self.chain.w3.eth.get_code.return_value = b""
        self.chain.w3.eth.get_balance.return_value = 10**22
        self.chain.w3.eth.get_transaction_count.return_value = 0
        self.chain.w3.eth.estimate_gas.return_value = 21000
        self.chain.w3.eth.get_block.side_effect = lambda height, **kw: {
            "number": 100 if height in {"latest", "finalized"} else height,
            "hash": b"\x22" * 32,
            "transactions": [],
            "timestamp": int(time.time()) - 30,
        }
        self.chain.w3.provider.make_request.return_value = {
            "result": {"instanceId": "guardrail-test-1"}
        }
        self.chain.network_manager = MagicMock()
        self.chain.network_manager.load_deployment_manifest.return_value = (
            [],
            {"contractAddress": "0x" + "aa" * 20, "runtimeCodeHash": "0x" + "bb" * 32},
        )
        self.chain.network_manager.verify_contract_bytecode.return_value = True
        self.chain.get_token_balance.return_value = {
            "balance": "1000",
            "symbol": "AGNT",
            "token_address": "0x" + "aa" * 20,
        }
        self.chain.prepare_native_transfer.side_effect = lambda sender, recipient, amount: {
            "transaction": {
                "from": sender,
                "to": recipient,
                "value": int(float(amount) * 10**18),
                "nonce": 0,
                "chainId": 31337,
                "gas": 21000,
                "gasPrice": 10**9,
            }
        }
        self.chain.get_native_balance.return_value = {
            "balance": "50.0",
            "raw_balance": str(50 * 10**18),
            "symbol": "ETH",
            "address": self.a.address,
        }

        # Base policy allows up to 2.0 ETH native and 500 AGNT
        self.base_config = PolicyConfig(
            max_native_transfer_limit=Decimal("2.0"),
            max_daily_native_transfer_limit=Decimal("10.0"),
            max_token_transfer_limit=Decimal("500"),
            max_daily_token_transfer_limit=Decimal("2000"),
            recipient_whitelist=[self.recipient_1],
            enforce_whitelist=True,
            require_human_approval_for_writes=True,
        )
        self.policy = PolicyEngine(self.base_config)
        self.llm = FakeLLMProvider([LLMResponse(content="OK")])
        self.settings = WalletSettings(self.url, origin=ORIGIN, browser_writes=True)
        self.app = create_app(
            profile="unit",
            agent_mode="llm",
            enable_local_writes=False,
            blockchain=self.chain,
            policy=self.policy,
            wallet_settings=self.settings,
            llm=self.llm,
            retriever=MagicMock(scope=SourceScope("v1"), retrieve=AsyncMock(return_value=[])),
            agent_settings=Settings(_env_file=None, llm_provider="fake"),
        )
        self.client_a = self.enterContext(TestClient(self.app))
        self.client_a.headers["origin"] = ORIGIN

        self.client_b = self.enterContext(TestClient(self.app))
        self.client_b.headers["origin"] = ORIGIN

    def login(self, account, client):
        challenge = client.post(
            "/api/auth/challenge", json={"address": account.address, "chain_id": 31337}
        )
        self.assertEqual(challenge.status_code, 200, challenge.text)
        payload = challenge.json()
        signature = Account.sign_message(
            encode_defunct(text=payload["message"]), account.key
        ).signature.hex()
        verified = client.post(
            "/api/auth/verify",
            json={"challenge_id": payload["challenge_id"], "signature": signature},
        )
        self.assertEqual(verified.status_code, 200, verified.text)
        client.headers["x-csrf-token"] = client.cookies["ati_csrf"]
        context = client.post("/api/wallet-contexts", json={"chain_id": 31337})
        self.assertEqual(context.status_code, 200, context.text)
        return context.json()

    def create_conversation(self, client, context):
        res = client.post(
            "/api/history/conversations",
            json={
                "context_id": context["id"],
                "generation": context["generation"],
                "title": "Guardrail Test Chat",
            },
        )
        self.assertEqual(res.status_code, 200, res.text)
        return res.json()["id"]

    def test_1_guardrail_config_persistence_and_runtime_effect(self):
        """1. Kiểm tra việc đổi cấu hình Guardrail có hiệu lực ngay ở yêu cầu tiếp theo và không bị mất dữ liệu khi tải lại."""
        ctx_a = self.login(self.a, self.client_a)
        conv_a = self.create_conversation(self.client_a, ctx_a)

        # GET default config
        res = self.client_a.get(f"/api/guardrail/config?wallet_address={self.a.address}")
        self.assertEqual(res.status_code, 200)
        cfg = res.json()
        self.assertEqual(cfg["per_tx_native_limit"], 2.0)

        # PUT updated config: lower limit to 1.0 ETH, enforce whitelist with recipient_1 only
        update_payload = {
            "wallet_address": self.a.address,
            "per_tx_native_limit": 1.0,
            "daily_native_limit": 5.0,
            "token_limits": {
                "0x" + "aa" * 20: {"per_tx_limit": 200.0, "daily_limit": 800.0, "symbol": "AGNT"}
            },
            "recipient_whitelist": [self.recipient_1],
            "enforce_whitelist": True,
            "require_app_approval": True,
            "approval_timeout_seconds": 600,
        }
        put_res = self.client_a.put("/api/guardrail/config", json=update_payload)
        self.assertEqual(put_res.status_code, 200, put_res.text)
        self.assertEqual(put_res.json()["status"], "SAVED")

        # Verify durable persistence: Read back config from fresh GET request
        get_res2 = self.client_a.get(f"/api/guardrail/config?wallet_address={self.a.address}")
        self.assertEqual(get_res2.status_code, 200)
        c2 = get_res2.json()
        self.assertEqual(c2["per_tx_native_limit"], 1.0)
        self.assertEqual(c2["daily_native_limit"], 5.0)
        self.assertEqual(c2["token_address"].lower(), "0x" + "aa" * 20)
        self.assertEqual(c2["per_tx_token_limit"], 200.0)
        self.assertEqual(c2["daily_token_limit"], 800.0)
        self.assertEqual(Decimal(c2["daily_token_remaining"]), Decimal("800"))
        token_check = self.client_a.post(
            "/api/guardrail/test-block",
            json={"wallet_address": self.a.address, "operation": "erc20_transfer",
                  "amount": "201", "recipient": self.recipient_1},
        )
        self.assertEqual(token_check.status_code, 200, token_check.text)
        self.assertEqual(token_check.json()["decision"], "BLOCK")
        self.assertTrue(c2["enforce_whitelist"])
        self.assertIn(self.recipient_1, c2["recipient_whitelist"])

        # Also check directly in SQLite database table
        with self.app.state.wallet_db.transaction() as conn:
            dbrec = gc_repo.find_config(conn, self.a.address)
            self.assertIsNotNone(dbrec)
            self.assertEqual(dbrec["per_tx_native_limit"], "1.0")
            self.assertTrue(dbrec["enforce_whitelist"])

        # Verify immediate runtime effect on NEXT request:
        # Transfer 0.8 ETH to recipient_1: within 1.0 limit & on whitelist -> Allowed
        prop_allowed = self.client_a.post(
            "/api/wallet-proposals",
            json={
                "conversation_id": conv_a,
                "context_id": ctx_a["id"],
                "generation": ctx_a["generation"],
                "operation": "native_transfer",
                "amount": "0.8",
                "recipient": self.recipient_1,
            },
        )
        self.assertEqual(prop_allowed.status_code, 200, prop_allowed.text)
        self.assertTrue(prop_allowed.json()["is_allowed"])
        self.assertTrue(prop_allowed.json()["requires_approval"])

        # Transfer 1.5 ETH: exceeds the new 1.0 limit -> BLOCKED immediately!
        prop_blocked_amount = self.client_a.post(
            "/api/wallet-proposals",
            json={
                "conversation_id": conv_a,
                "context_id": ctx_a["id"],
                "generation": ctx_a["generation"],
                "operation": "native_transfer",
                "amount": "1.5",
                "recipient": self.recipient_1,
            },
        )
        self.assertEqual(prop_blocked_amount.status_code, 200)
        self.assertFalse(prop_blocked_amount.json()["is_allowed"])
        self.assertTrue(
            any("exceeds native transfer limit" in v for v in prop_blocked_amount.json()["violations"])
        )

        # Transfer 0.5 ETH to recipient_2 (not in whitelist when enforce_whitelist=True) -> BLOCKED immediately!
        prop_blocked_whitelist = self.client_a.post(
            "/api/wallet-proposals",
            json={
                "conversation_id": conv_a,
                "context_id": ctx_a["id"],
                "generation": ctx_a["generation"],
                "operation": "native_transfer",
                "amount": "0.5",
                "recipient": self.recipient_2,
            },
        )
        self.assertEqual(prop_blocked_whitelist.status_code, 200)
        self.assertFalse(prop_blocked_whitelist.json()["is_allowed"])
        self.assertTrue(
            any("NOT in the authorized whitelist" in v for v in prop_blocked_whitelist.json()["violations"])
        )

    def test_2_cross_wallet_configuration_modification_rejected(self):
        """2. Kiểm tra cơ chế bảo mật đảm bảo một địa chỉ ví khác không thể gọi API sửa cấu hình của ví hiện tại."""
        ctx_a = self.login(self.a, self.client_a)
        ctx_b = self.login(self.b, self.client_b)

        # Wallet A attempts to modify Wallet B's guardrail config
        attack_payload = {
            "wallet_address": self.b.address,  # Target is Wallet B
            "per_tx_native_limit": 999.0,
            "daily_native_limit": 9999.0,
            "token_limits": {},
            "recipient_whitelist": [],
            "enforce_whitelist": True,
            "require_app_approval": False,
            "approval_timeout_seconds": 600,
        }
        res = self.client_a.put("/api/guardrail/config", json=attack_payload)
        # Must return 403 Forbidden
        self.assertEqual(res.status_code, 403, res.text)
        self.assertEqual(res.json()["detail"]["code"], "FORBIDDEN")

        # Verify Wallet B's config in DB was NOT changed to attack_payload
        with self.app.state.wallet_db.transaction() as conn:
            cfg_b = gc_repo.find_config(conn, self.b.address)
            self.assertIsNone(cfg_b)  # Wallet B has not customized yet

        # Wallet B can modify Wallet B's own config successfully
        legit_payload = {
            "wallet_address": self.b.address,
            "per_tx_native_limit": 0.5,
            "daily_native_limit": 2.0,
            "token_limits": {},
            "recipient_whitelist": [self.recipient_2],
            "enforce_whitelist": True,
            "require_app_approval": True,
            "approval_timeout_seconds": 600,
        }
        res_b = self.client_b.put("/api/guardrail/config", json=legit_payload)
        self.assertEqual(res_b.status_code, 200, res_b.text)
        self.assertEqual(res_b.json()["status"], "SAVED")

        # Now Wallet B tries to modify Wallet A's config -> 403 Forbidden
        attack_back = dict(legit_payload, wallet_address=self.a.address)
        res_attack_back = self.client_b.put("/api/guardrail/config", json=attack_back)
        self.assertEqual(res_attack_back.status_code, 403)

    def test_3_test_block_decision_and_zero_side_effects(self):
        """3. Kiểm tra tính năng “Thử chặn” trả về đúng quyết định và lý do từ Policy Engine nhưng không phát sinh giao dịch và không cộng vào hạn mức đã dùng."""
        self.login(self.a, self.client_a)

        # Baseline check: count proposals and daily limit reservations in DB
        with self.app.state.wallet_db.transaction() as conn:
            proposals_before = len(list(conn.execute(select(proposals))))
            limits_before = len(list(conn.execute(select(limit_entries))))

        # Case A: Compliant request -> Decision: REQUIRE_APPROVAL
        res_pass = self.client_a.post(
            "/api/guardrail/test-block",
            json={
                "wallet_address": self.a.address,
                "operation": "native_transfer",
                "amount": "0.5",
                "recipient": self.recipient_1,
            },
        )
        self.assertEqual(res_pass.status_code, 200, res_pass.text)
        data_pass = res_pass.json()
        self.assertEqual(data_pass["decision"], "REQUIRE_APPROVAL")
        self.assertTrue(data_pass["is_allowed"])
        self.assertTrue(data_pass["requires_approval"])
        self.assertEqual(len(data_pass["reasons"]), 1)

        # Case B: Exceeds per-tx limit (3.0 > 2.0 default) -> Decision: BLOCK
        res_block_limit = self.client_a.post(
            "/api/guardrail/test-block",
            json={
                "wallet_address": self.a.address,
                "operation": "native_transfer",
                "amount": "3.0",
                "recipient": self.recipient_1,
            },
        )
        self.assertEqual(res_block_limit.status_code, 200)
        data_block = res_block_limit.json()
        self.assertEqual(data_block["decision"], "BLOCK")
        self.assertFalse(data_block["is_allowed"])
        self.assertTrue(any("exceeds native transfer limit" in r for r in data_block["reasons"]))

        # Case C: Invalid recipient address -> Decision: BLOCK
        res_block_addr = self.client_a.post(
            "/api/guardrail/test-block",
            json={
                "wallet_address": self.a.address,
                "operation": "native_transfer",
                "amount": "0.1",
                "recipient": "0xinvalid_address",
            },
        )
        self.assertEqual(res_block_addr.status_code, 200)
        data_addr = res_block_addr.json()
        self.assertEqual(data_addr["decision"], "BLOCK")
        self.assertFalse(data_addr["is_allowed"])

        # VERIFY ZERO SIDE EFFECTS:
        # Zero proposals created in database
        with self.app.state.wallet_db.transaction() as conn:
            proposals_after = len(list(conn.execute(select(proposals))))
            limits_after = len(list(conn.execute(select(limit_entries))))

        self.assertEqual(proposals_after, proposals_before, "Test-block must NOT create proposals!")
        self.assertEqual(limits_after, limits_before, "Test-block must NOT consume daily limits!")

    def test_4_proposal_created_before_policy_change_reevaluated(self):
        """4. Kiểm tra proposal tạo trước khi đổi policy buộc phải được đánh giá lại theo cấu hình mới trước khi cấp quyền ký."""
        ctx_a = self.login(self.a, self.client_a)
        conv_a = self.create_conversation(self.client_a, ctx_a)

        # Step 1: Create a proposal for 1.5 ETH (allowed under base limit of 2.0 ETH)
        prop_res = self.client_a.post(
            "/api/wallet-proposals",
            json={
                "conversation_id": conv_a,
                "context_id": ctx_a["id"],
                "generation": ctx_a["generation"],
                "operation": "native_transfer",
                "amount": "1.5",
                "recipient": self.recipient_1,
            },
        )
        self.assertEqual(prop_res.status_code, 200, prop_res.text)
        proposal_id = prop_res.json()["pending_approval"]["approval_id"]
        param_hash = prop_res.json()["pending_approval"]["parameter_hash"]

        # Step 2: Policy is CHANGED: Lower per_tx limit to 1.0 ETH (now 1.5 ETH is illegal)
        update_res = self.client_a.put(
            "/api/guardrail/config",
            json={
                "wallet_address": self.a.address,
                "per_tx_native_limit": 1.0,  # Lower than 1.5 ETH!
                "daily_native_limit": 5.0,
                "token_limits": {},
                "recipient_whitelist": [self.recipient_1],
                "enforce_whitelist": True,
                "require_app_approval": True,
                "approval_timeout_seconds": 600,
            },
        )
        self.assertEqual(update_res.status_code, 200)

        # Step 3: Wallet A tries to authorize the proposal created under the old policy
        auth_res = self.client_a.post(
            f"/api/wallet-proposals/{proposal_id}/authorize",
            json={
                "parameter_hash": param_hash,
                "context_id": ctx_a["id"],
                "generation": ctx_a["generation"],
            },
        )
        # MUST BE REJECTED because re-evaluation under new policy fails!
        self.assertEqual(auth_res.status_code, 409, auth_res.text)
        self.assertEqual(auth_res.json()["detail"]["code"], "POLICY_CHANGED")

        # Step 4: Now test the case where policy changed, but proposal STILL PASSES
        # Create a new proposal for 0.5 ETH (which is <= 1.0 ETH)
        prop_res2 = self.client_a.post(
            "/api/wallet-proposals",
            json={
                "conversation_id": conv_a,
                "context_id": ctx_a["id"],
                "generation": ctx_a["generation"],
                "operation": "native_transfer",
                "amount": "0.5",
                "recipient": self.recipient_1,
            },
        )
        self.assertEqual(prop_res2.status_code, 200, prop_res2.text)
        proposal_id2 = prop_res2.json()["pending_approval"]["approval_id"]
        param_hash2 = prop_res2.json()["pending_approval"]["parameter_hash"]

        # Policy changes slightly (e.g. daily limit updated from 5.0 to 4.0, but 0.5 still well within limits)
        update_res2 = self.client_a.put(
            "/api/guardrail/config",
            json={
                "wallet_address": self.a.address,
                "per_tx_native_limit": 1.0,
                "daily_native_limit": 4.0,
                "token_limits": {},
                "recipient_whitelist": [self.recipient_1],
                "enforce_whitelist": True,
                "require_app_approval": True,
                "approval_timeout_seconds": 300,
            },
        )
        self.assertEqual(update_res2.status_code, 200)

        # Authorize proposal 2:
        auth_res2 = self.client_a.post(
            f"/api/wallet-proposals/{proposal_id2}/authorize",
            json={
                "parameter_hash": param_hash2,
                "context_id": ctx_a["id"],
                "generation": ctx_a["generation"],
            },
        )
        # MUST SUCCEED because re-evaluation passes, updating policy_hash and reserving limit!
        self.assertEqual(auth_res2.status_code, 200, auth_res2.text)
        self.assertEqual(auth_res2.json()["status"], "AWAITING_SIGNATURE")
        self.assertIn("submission_id", auth_res2.json())


if __name__ == "__main__":
    unittest.main()
