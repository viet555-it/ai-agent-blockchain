"""Real signatures and durable storage, with deterministic RPC/LLM substitutes."""

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from web3 import Web3
from web3.exceptions import TransactionNotFound

from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider
from backend.api.server import create_app
from backend.db.schema_v1 import (
    attempts,
    challenges,
    messages,
    proposals,
    sessions,
    turns,
)
from backend.db.store import Database
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.services.blockchain_service import BlockchainService
from backend.wallet_settings import WalletSettings
from config.settings import Settings
from rag.retriever import SourceScope
from scripts.backup_app_db import backup

ORIGIN = "http://testserver"


class WalletHistoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.url = "sqlite:///" + (self.folder / "history.db").as_posix()
        database = Database(self.url)
        database.migrate()
        database.close()
        self.a, self.b = Account.create(), Account.create()
        self.recipient = Account.create().address
        self.chain = MagicMock(spec=BlockchainService)
        self.chain.chain_id = 31337
        self.chain.rpc_url = "http://127.0.0.1:8545"
        self.chain.validate_and_checksum_address.side_effect = Web3.to_checksum_address
        self.chain.w3 = MagicMock()
        self.chain.w3.eth.chain_id = 31337
        self.chain.w3.eth.block_number = 10
        self.chain.w3.eth.get_code.return_value = b""
        self.chain.w3.eth.get_balance.return_value = 10**22
        self.chain.w3.eth.get_transaction_count.return_value = 0
        self.chain.w3.eth.estimate_gas.return_value = 21000
        self.chain.w3.eth.get_block.side_effect = lambda height, **kw: {
            "number": 10 if height in {"latest", "finalized"} else height,
            "hash": b"\x11" * 32,
            "transactions": [],
        }
        self.chain.w3.provider.make_request.return_value = {
            "result": {"instanceId": "test-instance-1"}
        }
        self.chain.network_manager = MagicMock()
        self.chain.network_manager.load_deployment_manifest.return_value = (
            [],
            {"contractAddress": "0x" + "12" * 20, "runtimeCodeHash": "0x" + "34" * 32},
        )
        self.chain.network_manager.verify_contract_bytecode.return_value = True
        self.chain.get_token_balance.return_value = {
            "balance": "10",
            "symbol": "AGNT",
            "token_address": "0x" + "12" * 20,
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
            "balance": "10.000000000000000001",
            "raw_balance": "10000000000000000001",
            "symbol": "ETH",
            "address": self.a.address,
        }
        self.policy = PolicyEngine(PolicyConfig(recipient_whitelist=[self.recipient]))
        self.llm = FakeLLMProvider(
            [LLMResponse(content="Saved reply"), LLMResponse(content="Restored reply")]
        )
        self.settings = WalletSettings(self.url, origin=ORIGIN, browser_writes=True)
        self.app = self.make_app()
        self.client = self.enterContext(TestClient(self.app))
        self.client.headers["origin"] = ORIGIN

    def make_app(self):
        return create_app(
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

    def login(self, account=None, client=None):
        account, client = account or self.a, client or self.client
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
        return context.json(), payload, signature

    def conversation(self, context):
        result = self.client.post(
            "/api/history/conversations",
            json={
                "context_id": context["id"],
                "generation": context["generation"],
                "title": "private A",
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()["id"]

    def propose(self, context, conversation):
        response = self.client.post(
            "/api/wallet-proposals",
            json={
                "context_id": context["id"],
                "generation": context["generation"],
                "conversation_id": conversation,
                "operation": "native_transfer",
                "amount": "0.001",
                "recipient": self.recipient,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["requires_approval"], response.text)
        return response.json()["pending_approval"]

    def review_body(self, context, proposal):
        return {
            "context_id": context["id"],
            "generation": context["generation"],
            "parameter_hash": proposal["parameter_hash"],
        }

    def test_origin_csrf_replay_and_wallet_signature(self):
        self.assertEqual(self.client.get("/api/history/conversations").status_code, 401)
        denied = self.client.post(
            "/api/auth/challenge",
            headers={"origin": "https://attacker.invalid"},
            json={"address": self.a.address, "chain_id": 31337},
        )
        self.assertEqual(denied.status_code, 403)
        context, challenge, signature = self.login()
        replay = self.client.post(
            "/api/auth/verify",
            json={"challenge_id": challenge["challenge_id"], "signature": signature},
        )
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(
            self.client.post(
                "/api/wallet-contexts", headers={"x-csrf-token": "wrong"}, json={"chain_id": 31337}
            ).status_code,
            403,
        )
        self.assertEqual(self.client.get("/api/auth/me").json()["address"], self.a.address)
        self.assertEqual(self.client.get("/api/auth/me").headers["cache-control"], "no-store")

    def test_wallet_assets_use_the_browser_deployment_contract(self):
        response = self.client.get("/api/wallet/info", params={"address": self.a.address})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["token_address"], "0x" + "12" * 20)
        self.assertEqual(response.json()["token_balance"], "10")

    def test_stale_deployment_gives_recovery_instructions_without_losing_history(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        manifest = self.chain.network_manager.load_deployment_manifest.return_value[1]
        manifest["transactionHash"] = "0x" + "ab" * 32
        self.chain.w3.eth.get_transaction_receipt.side_effect = TransactionNotFound("missing")
        response = self.client.post("/api/wallet-contexts", json={"chain_id": 31337})
        self.assertEqual(response.status_code, 503, response.text)
        detail = response.json()["detail"]
        self.assertEqual(detail["code"], "DEPLOYMENT_UNAVAILABLE")
        self.assertIn("scripts.setup_local_demo", detail["message"])
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        history = self.client.get("/api/history/conversations").json()
        self.assertIn(conversation, [item["id"] for item in history["items"]])

    def test_missing_contract_code_gives_deployment_error(self):
        self.login()
        self.chain.network_manager.verify_contract_bytecode.side_effect = ValueError("no code")
        response = self.client.post("/api/wallet-contexts", json={"chain_id": 31337})
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["detail"]["code"], "DEPLOYMENT_UNAVAILABLE")

    def test_frontend_revalidates_assets_so_old_wallet_controls_are_not_cached(self):
        for path in ["/", "/app.js", "/styles.css", "/ui/chat.js", "/styles/chat.css"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-cache")

    def test_invalid_signature_and_expired_challenge(self):
        challenge = self.client.post(
            "/api/auth/challenge", json={"address": self.a.address, "chain_id": 31337}
        ).json()
        wrong = Account.sign_message(
            encode_defunct(text=challenge["message"]), self.b.key
        ).signature.hex()
        self.assertEqual(
            self.client.post(
                "/api/auth/verify",
                json={"challenge_id": challenge["challenge_id"], "signature": wrong},
            ).status_code,
            401,
        )
        with self.app.state.wallet_db.transaction() as connection:
            connection.execute(update(challenges).values(expires_at=0))
        signed = Account.sign_message(
            encode_defunct(text=challenge["message"]), self.a.key
        ).signature.hex()
        self.assertEqual(
            self.client.post(
                "/api/auth/verify",
                json={"challenge_id": challenge["challenge_id"], "signature": signed},
            ).status_code,
            401,
        )

    def test_switch_wallet_isolates_history_and_revokes_old_proposal(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        proposal = self.propose(context, conversation)
        self.login(self.b)
        self.assertEqual(self.client.get("/api/history/conversations").json()["items"], [])
        self.assertEqual(
            self.client.get(f"/api/history/conversations/{conversation}/messages").status_code, 404
        )
        self.assertEqual(
            self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").status_code, 404
        )
        self.login(self.a)
        saved = self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").json()
        self.assertEqual(saved["status"], "CANCELLED")
        self.assertEqual(len(self.client.get("/api/history/conversations").json()["items"]), 1)
        self.chain.w3.eth.send_transaction.assert_not_called()

    def test_chat_retry_reload_restart_context_and_backup(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        body = dict(
            query="Remember this",
            context_id=context["id"],
            generation=1,
            client_request_id="request-1",
        )
        result = self.client.post(f"/api/history/conversations/{conversation}/turns", json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "COMPLETED", result.text)
        repeated = self.client.post(f"/api/history/conversations/{conversation}/turns", json=body)
        self.assertEqual(repeated.json(), result.json())
        self.assertEqual(self.llm.total_calls, 1)
        # A new app instance has no RAM sessions but shares the persisted cookie/database.
        with TestClient(self.make_app()) as restarted:
            restarted.cookies.update(self.client.cookies)
            restarted.headers.update(
                {"origin": ORIGIN, "x-csrf-token": self.client.cookies["ati_csrf"]}
            )
            history = restarted.get(f"/api/history/conversations/{conversation}/messages").json()
            self.assertEqual(
                history["items"][0]["messages"][1]["content"], result.json()["response"]["reply"]
            )
            body.update(query="What did I say?", client_request_id="request-2")
            result = restarted.post(f"/api/history/conversations/{conversation}/turns", json=body)
            self.assertEqual(result.json()["status"], "COMPLETED", result.text)
            model_messages = self.llm.call_history[-1]["messages"]
            self.assertIn("Remember this", [item.get("content") for item in model_messages])
        snapshot = backup(self.url, self.folder / "backup.db")
        restored = Database("sqlite:///" + snapshot.as_posix())
        restored.check_schema()
        with restored.transaction() as connection:
            self.assertEqual(len(list(connection.execute(select(turns)))), 2)
        restored.close()

    def test_authorize_tamper_duplicate_and_never_broadcasts(self):
        context, _, _ = self.login()
        proposal = self.propose(context, self.conversation(context))
        path = f"/api/wallet-proposals/{proposal['approval_id']}/authorize"
        body = self.review_body(context, proposal)
        denied = self.client.post(path, json={**body, "parameter_hash": "0" * 64})
        self.assertEqual(denied.status_code, 409)
        accepted = self.client.post(path, json=body)
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(self.client.post(path, json=body).status_code, 409)
        self.chain.w3.eth.send_transaction.assert_not_called()
        self.chain.w3.eth.send_raw_transaction.assert_not_called()
        self.assertIn("report_token", accepted.json())
        history = self.client.get("/api/history/transactions").json()
        self.assertNotIn("report_hash", json.dumps(history))

    def test_context_revoke_blocks_stale_requests(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        proposal = self.propose(context, conversation)
        self.client.post(f"/api/wallet-contexts/{context['id']}/revoke")
        denied = self.client.post(
            f"/api/wallet-proposals/{proposal['approval_id']}/authorize",
            json=self.review_body(context, proposal),
        )
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(
            self.client.post(
                f"/api/history/conversations/{conversation}/turns",
                json={
                    "query": "late request",
                    "context_id": context["id"],
                    "generation": 1,
                    "client_request_id": "late",
                },
            ).status_code,
            409,
        )

    def test_late_report_after_switch_stays_with_original_owner(self):
        context, _, _ = self.login()
        proposal = self.propose(context, self.conversation(context))
        result = self.client.post(
            f"/api/wallet-proposals/{proposal['approval_id']}/authorize",
            json=self.review_body(context, proposal),
        ).json()
        self.login(self.b)
        path = f"/api/wallet-submissions/{result['submission_id']}/report"
        tx_hash = "0x" + "ab" * 32
        self.assertEqual(
            self.client.post(
                path, json={"report_token": "wrong" * 8, "tx_hash": tx_hash}
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                path, json={"report_token": result["report_token"], "tx_hash": tx_hash}
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/history/transactions").json()["items"], [])
        self.login(self.a)
        self.assertEqual(
            self.client.get("/api/history/transactions").json()["items"][0]["tx_hash"], tx_hash
        )

    def test_unknown_blocks_second_send_and_restart_keeps_it(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        first = self.propose(context, conversation)
        self.client.post(
            f"/api/wallet-proposals/{first['approval_id']}/authorize",
            json=self.review_body(context, first),
        )
        second = self.propose(context, conversation)
        result = self.client.post(
            f"/api/wallet-proposals/{second['approval_id']}/authorize",
            json=self.review_body(context, second),
        )
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["detail"]["code"], "WALLET_BUSY")
        with self.app.state.wallet_db.transaction() as connection:
            self.assertEqual(len(list(connection.execute(select(attempts)))), 1)
            self.assertEqual(
                connection.execute(
                    select(proposals.c.status).where(proposals.c.id == second["approval_id"])
                ).scalar(),
                "PENDING_REVIEW",
            )

    def test_hardhat_reset_invalidates_old_context(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        self.chain.w3.provider.make_request.return_value = {
            "result": {"instanceId": "reset-instance"}
        }
        response = self.client.post(
            f"/api/history/conversations/{conversation}/turns",
            json={
                "query": "stale",
                "context_id": context["id"],
                "generation": 1,
                "client_request_id": "reset",
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_old_demo_endpoints_disabled_and_no_session_token_in_database(self):
        self.login()
        self.assertEqual(self.client.post("/api/chat", json={"query": "balance"}).status_code, 403)
        self.assertEqual(self.client.get("/api/guardrail/audits").status_code, 403)
        with self.app.state.wallet_db.transaction() as connection:
            stored = str(list(connection.execute(select(sessions))))
        self.assertNotIn(self.client.cookies["ati_session"], stored)

    def test_tool_protocol_saved_without_thought_text(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        self.llm._responses = [
            LLMResponse(
                content="INTERNAL THOUGHT MUST NOT PERSIST",
                tool_calls=[
                    ToolCall(
                        id="balance",
                        name="get_native_balance",
                        arguments={"address": self.a.address},
                    )
                ],
            ),
            LLMResponse(content="Your balance is available."),
        ]
        result = self.client.post(
            f"/api/history/conversations/{conversation}/turns",
            json={
                "query": "balance",
                "context_id": context["id"],
                "generation": 1,
                "client_request_id": "tool",
            },
        )
        self.assertEqual(result.json()["status"], "COMPLETED", result.text)
        with self.app.state.wallet_db.transaction() as connection:
            data = list(connection.execute(select(messages.c.data)).scalars())
        self.assertNotIn("INTERNAL THOUGHT MUST NOT PERSIST", json.dumps(data))
        self.assertIn('"tool_call_id": "balance"', json.dumps(data))

    def submitted(self):
        context, _, _ = self.login()
        proposal = self.propose(context, self.conversation(context))
        response = self.client.post(
            f"/api/wallet-proposals/{proposal['approval_id']}/authorize",
            json=self.review_body(context, proposal),
        )
        self.assertEqual(response.status_code, 200, response.text)
        submission = response.json()
        tx_hash = "0x" + "cd" * 32
        tx = {
            key: int(value) if key in {"value", "gas", "gasPrice", "nonce", "chainId"} else value
            for key, value in submission["transaction"].items()
        }
        tx.update(hash=tx_hash, blockNumber=10, input="0x")
        receipt = {
            "status": 1,
            "blockNumber": 10,
            "blockHash": b"\x11" * 32,
            "transactionHash": tx_hash,
            "from": self.a.address,
            "to": self.recipient,
            "gasUsed": 21000,
        }
        self.chain.w3.eth.get_transaction.return_value = tx
        self.chain.w3.eth.get_transaction_receipt.return_value = receipt
        result = self.client.post(
            f"/api/wallet-submissions/{submission['submission_id']}/report",
            json={"report_token": submission["report_token"], "tx_hash": tx_hash},
        )
        self.assertEqual(result.status_code, 200, result.text)
        return proposal, submission, tx, receipt

    def poll_now(self):
        with self.app.state.wallet_db.transaction() as connection:
            connection.execute(update(attempts).values(next_check_at=0))
        self.app.state.browser_wallet.reconcile_batch()

    def test_receipt_is_verified_and_revert_is_not_success(self):
        proposal, submission, tx, receipt = self.submitted()
        receipt["status"] = 0
        self.poll_now()
        result = self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").json()
        attempt = result["attempts"][0]
        self.assertEqual(attempt["verification_status"], "MATCHED", result)
        self.assertEqual(attempt["status"], "FINALIZED", result)
        self.assertEqual(attempt["receipt"]["receipt_status"], 0)

    def test_reorg_removes_stale_receipt_and_returns_to_submitted(self):
        proposal, submission, tx, receipt = self.submitted()
        self.chain.w3.eth.get_block.side_effect = lambda height, **kw: {
            "number": 9 if height == "finalized" else height,
            "hash": b"\x11" * 32,
            "transactions": [],
        }
        self.poll_now()
        result = self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").json()
        self.assertEqual(result["attempts"][0]["status"], "MINED_SUCCESS", result)
        self.chain.w3.eth.get_block.side_effect = lambda height, **kw: {
            "number": 9 if height == "finalized" else height,
            "hash": b"\x22" * 32 if height == 10 else b"\x11" * 32,
            "transactions": [],
        }
        self.poll_now()
        result = self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").json()
        self.assertEqual(result["attempts"][0]["status"], "SUBMITTED", result)
        self.assertIsNone(result["attempts"][0]["receipt"])

    def test_replacement_is_a_separate_attempt_and_changed_value_is_mismatched(self):
        proposal, submission, tx, receipt = self.submitted()
        replacement_hash = "0x" + "ef" * 32
        tx.update(hash=replacement_hash, value=tx["value"] + 1)
        receipt["transactionHash"] = replacement_hash

        def get_transaction(tx_hash):
            if tx_hash != replacement_hash:
                raise TransactionNotFound("not found")
            return tx

        self.chain.w3.eth.get_transaction.side_effect = get_transaction
        self.chain.w3.eth.get_transaction_count.return_value = 1
        self.chain.w3.eth.get_block.side_effect = lambda height, **kw: {
            "number": 10 if height == "finalized" else height,
            "hash": b"\x11" * 32,
            "transactions": [tx] if kw.get("full_transactions") else [],
        }
        self.poll_now()
        self.poll_now()
        result = self.client.get(f"/api/wallet-proposals/{proposal['approval_id']}").json()
        self.assertEqual(len(result["attempts"]), 2, result)
        self.assertEqual(result["attempts"][0]["status"], "REPLACED", result)
        self.assertEqual(result["attempts"][1]["verification_status"], "MISMATCHED", result)
        self.assertEqual(result["attempts"][1]["replaces_id"], submission["submission_id"])

    def test_concurrent_authorization_only_grants_one_submission(self):
        context, _, _ = self.login()
        proposal = self.propose(context, self.conversation(context))
        path = f"/api/wallet-proposals/{proposal['approval_id']}/authorize"
        body = self.review_body(context, proposal)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: self.client.post(path, json=body), range(2)))
        self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
        with self.app.state.wallet_db.transaction() as connection:
            self.assertEqual(len(list(connection.execute(select(attempts)))), 1)

    def test_hash_recovery_is_owner_only(self):
        proposal, submission, tx, receipt = self.submitted()
        self.login(self.b)
        recovered = self.client.post(
            f"/api/wallet-submissions/{submission['submission_id']}/recover",
            json={"tx_hash": tx["hash"]},
        )
        self.assertEqual(recovered.status_code, 404)

    def test_explicit_signature_rejection_after_poll_releases_send_lock(self):
        context, _, _ = self.login()
        conversation = self.conversation(context)
        proposal = self.propose(context, conversation)
        submission = self.client.post(
            f"/api/wallet-proposals/{proposal['approval_id']}/authorize",
            json=self.review_body(context, proposal),
        ).json()
        self.poll_now()
        result = self.client.post(
            f"/api/wallet-submissions/{submission['submission_id']}/report",
            json={"report_token": submission["report_token"], "rejected": True},
        )
        self.assertEqual(result.status_code, 200, result.text)
        next_proposal = self.propose(context, conversation)
        result = self.client.post(
            f"/api/wallet-proposals/{next_proposal['approval_id']}/authorize",
            json=self.review_body(context, next_proposal),
        )
        self.assertEqual(result.status_code, 200, result.text)
