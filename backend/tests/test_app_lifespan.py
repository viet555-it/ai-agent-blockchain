"""Resource ownership must hold on startup failure as well as normal shutdown."""

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.api.server import create_app
from backend.bootstrap.lifespan import reconcile_wallet
from backend.wallet_errors import WalletError, WalletErrorKind
from backend.wallet_settings import WalletSettings
from config.settings import Settings
from rag.models import DeploymentScope
from rag.retriever import SourceScope


class AppLifespanTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.blockchain = MagicMock(chain_id=31337)
        self.llm = MagicMock(aclose=AsyncMock())
        self.retriever = MagicMock(scope=SourceScope("v1"), aclose=AsyncMock())
        self.settings = Settings(_env_file=None, llm_provider="fake")
        self.enterContext(patch("backend.agent.read_runtime.ReadAgentRuntime"))

    def app(self, **overrides):
        options = dict(
            profile="unit",
            blockchain=self.blockchain,
            agent_mode="llm",
            agent_settings=self.settings,
        )
        options.update(overrides)
        return create_app(**options)

    def own_resources(self):
        self.enterContext(patch("agent.service._create_llm", return_value=self.llm))
        self.enterContext(
            patch("rag.retriever.RAGRetriever.create", AsyncMock(return_value=self.retriever))
        )

    async def test_owned_resources_close_once_after_normal_shutdown(self):
        self.own_resources()
        app = self.app()
        async with app.router.lifespan_context(app):
            self.llm.aclose.assert_not_awaited()
            self.retriever.aclose.assert_not_awaited()
        self.llm.aclose.assert_awaited_once()
        self.retriever.aclose.assert_awaited_once()

    async def test_receipt_worker_logs_domain_failure_and_schedules_retry(self):
        browser, history = MagicMock(), MagicMock()
        browser.reconcile_batch.side_effect = WalletError(
            WalletErrorKind.DEPENDENCY_UNAVAILABLE,
            "DEPLOYMENT_UNAVAILABLE",
            "Deployment is temporarily unavailable.",
        )
        with (
            patch(
                "backend.bootstrap.lifespan.asyncio.sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ) as sleep,
            self.assertLogs("backend.api", level="WARNING") as logs,
            self.assertRaises(asyncio.CancelledError),
        ):
            await reconcile_wallet(browser, history)
        browser.reconcile_batch.assert_called_once()
        history.recover.assert_not_called()
        sleep.assert_awaited_once_with(15)
        self.assertIn("DEPLOYMENT_UNAVAILABLE", logs.output[0])

    async def test_invalid_scope_closes_resources_acquired_before_startup_failure(self):
        self.own_resources()
        self.retriever.scope = DeploymentScope(
            11155111, "0x" + "11" * 20, "sha256:" + "a" * 64, "v1"
        )
        app = self.app()
        with self.assertRaisesRegex(ValueError, "SourceScope"):
            async with app.router.lifespan_context(app):
                self.fail("Invalid retrieval scope must prevent startup")
        self.llm.aclose.assert_awaited_once()
        self.retriever.aclose.assert_awaited_once()

    async def test_injected_resources_remain_owned_by_caller(self):
        app = self.app(llm=self.llm, retriever=self.retriever)
        async with app.router.lifespan_context(app):
            pass
        self.llm.aclose.assert_not_awaited()
        self.retriever.aclose.assert_not_awaited()

    async def test_failed_retriever_creation_still_closes_owned_llm(self):
        self.own_resources()
        with patch(
            "rag.retriever.RAGRetriever.create",
            AsyncMock(side_effect=RuntimeError("index offline")),
        ):
            app = self.app()
            with self.assertRaisesRegex(RuntimeError, "index offline"):
                async with app.router.lifespan_context(app):
                    self.fail("Unavailable index must prevent startup")
        self.llm.aclose.assert_awaited_once()
        self.retriever.aclose.assert_not_awaited()

    async def test_failed_cleanup_does_not_skip_other_resource_closes(self):
        self.own_resources()
        self.retriever.aclose.side_effect = RuntimeError("retriever close failed")
        app = self.app()
        with self.assertRaisesRegex(RuntimeError, "retriever close failed"):
            async with app.router.lifespan_context(app):
                pass
        self.llm.aclose.assert_awaited_once()

    async def test_database_schema_failure_releases_all_acquired_resources(self):
        self.own_resources()
        database = MagicMock()
        database.check_schema.side_effect = RuntimeError("migration required")
        with patch("backend.db.store.Database", return_value=database):
            app = self.app(wallet_settings=WalletSettings("sqlite:///:memory:"))
            with self.assertRaisesRegex(RuntimeError, "migration required"):
                async with app.router.lifespan_context(app):
                    self.fail("Missing schema must prevent startup")
        database.close.assert_called_once()
        self.retriever.aclose.assert_awaited_once()
        self.llm.aclose.assert_awaited_once()

    async def test_receipt_worker_stops_before_database_and_providers_close(self):
        self.own_resources()
        events = []
        started = asyncio.Event()

        async def worker(browser, history):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                events.append("worker stopped")

        database = MagicMock()
        database.close.side_effect = lambda: events.append("database closed")
        self.retriever.aclose.side_effect = lambda: events.append("retriever closed")
        self.llm.aclose.side_effect = lambda: events.append("llm closed")
        with (
            patch("backend.db.store.Database", return_value=database),
            patch("backend.services.wallet_auth.WalletAuth"),
            patch("backend.services.history_service.HistoryService"),
            patch("backend.services.browser_wallet.BrowserWalletService"),
            patch("backend.bootstrap.lifespan.reconcile_wallet", worker),
        ):
            app = self.app(wallet_settings=WalletSettings("sqlite:///:memory:"))
            async with app.router.lifespan_context(app):
                await asyncio.wait_for(started.wait(), timeout=2)
        self.assertEqual(
            events, ["worker stopped", "database closed", "retriever closed", "llm closed"]
        )
