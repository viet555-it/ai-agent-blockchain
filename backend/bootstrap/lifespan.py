"""Assemble runtime services and release resources owned by this application."""

import asyncio
import logging
import os
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from backend.agent.agent_service import BlockchainAgent
from backend.bootstrap.runtime import ApplicationRuntime
from backend.services.blockchain_service import BlockchainService
from backend.services.transaction_coordinator import TransactionCoordinator

logger = logging.getLogger("backend.api")


async def reconcile_wallet(browser: Any, history: Any) -> None:
    while True:
        try:
            await asyncio.to_thread(browser.reconcile_batch)
            await asyncio.to_thread(history.recover)
        except asyncio.CancelledError:
            raise
        except HTTPException as error:
            logger.warning("Wallet receipt reconciliation deferred: %s", error.detail)
        except Exception:
            logger.warning("Wallet receipt reconciliation deferred; dependencies unavailable")
        await asyncio.sleep(15)


async def stop_reconciliation(task: asyncio.Task) -> None:
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def start_wallet_history(
    app: FastAPI,
    runtime: ApplicationRuntime,
    blockchain: Any,
    retriever: Any,
    llm: Any,
    settings: Any,
    resources: AsyncExitStack,
) -> None:
    from backend.agent.read_runtime import ReadAgentRuntime
    from backend.db.store import Database
    from backend.services.browser_wallet import BrowserWalletService
    from backend.services.history_service import HistoryService
    from backend.services.wallet_auth import WalletAuth

    wallet_settings = runtime.wallet_settings
    database = Database(wallet_settings.database_url)
    resources.callback(database.close)
    database.check_schema()
    app.state.wallet_db = database
    app.state.wallet_auth = WalletAuth(
        database, wallet_settings, runtime.profile.chain_id, blockchain
    )
    app.state.history = HistoryService(database)
    app.state.history.recover()
    browser = BrowserWalletService(database, wallet_settings, blockchain, runtime.policy)
    runtime.network_manager.get_network_config().default_contracts["AgentToken"] = (
        browser.contract_address
    )
    app.state.browser_wallet = browser
    app.state.history_runtime = ReadAgentRuntime(
        blockchain=blockchain,
        retriever=retriever,
        llm=llm,
        settings=settings,
        transactions=browser if wallet_settings.browser_writes else None,
    )
    receipt_task = asyncio.create_task(reconcile_wallet(browser, app.state.history))
    resources.push_async_callback(stop_reconciliation, receipt_task)


def build_lifespan(
    runtime: ApplicationRuntime,
    *,
    root: Path,
    blockchain: BlockchainService | None = None,
    llm: Any = None,
    retriever: Any = None,
    agent_settings: Any = None,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal blockchain
        if blockchain is None:
            if runtime.profile.name == "unit":
                raise RuntimeError("unit profile requires an injected blockchain service")
            blockchain = BlockchainService(
                network_manager=runtime.network_manager, chain_id=runtime.profile.chain_id
            )
        if blockchain.chain_id != runtime.profile.chain_id:
            raise ValueError("Injected blockchain service does not match the runtime chain")
        transactions = None
        if runtime.local_writes and not runtime.history_enabled:
            transactions = TransactionCoordinator(blockchain, runtime.policy, runtime.wallet)
        elif runtime.sepolia_execution is not None:
            from backend.services.sepolia_execution import SepoliaTransactionCoordinator

            transactions = SepoliaTransactionCoordinator(
                blockchain, runtime.policy, runtime.sepolia_execution
            )
        if transactions is not None:
            runtime.network_manager.get_network_config().default_contracts["AgentToken"] = (
                transactions.contract_address
            )
        app.state.transactions = transactions
        app.state.agent = BlockchainAgent(
            blockchain_service=blockchain,
            policy_engine=runtime.policy,
            rag_adapter=runtime.rag,
            default_wallet=runtime.wallet,
        )
        app.state.blockchain = blockchain
        async with AsyncExitStack() as resources:
            if runtime.agent_mode == "llm":
                from agent.service import _create_llm
                from backend.agent.read_runtime import ReadAgentRuntime
                from backend.bootstrap.retrieval import create_retriever, validate_retriever
                from config.settings import Settings

                settings = agent_settings or Settings(
                    _env_file=None,
                    llm_provider=os.environ.get("LLM_PROVIDER", "fake"),
                    llm_model=os.environ.get("LLM_MODEL", ""),
                    gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
                    anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                    openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                    wallet_private_key="",
                    dry_run=True,
                )
                if llm is None and settings.llm_provider != "fake" and not settings.llm_model:
                    raise ValueError(
                        "Set an explicit active LLM_MODEL before enabling a real provider"
                    )
                selected_llm = llm if llm is not None else _create_llm(settings)
                if llm is None and hasattr(selected_llm, "aclose"):
                    resources.push_async_callback(selected_llm.aclose)
                selected_retriever = retriever
                if selected_retriever is None:
                    selected_retriever = await create_retriever(runtime, root)
                    resources.push_async_callback(selected_retriever.aclose)
                validate_retriever(runtime, selected_retriever, root)
                app.state.read_agent = ReadAgentRuntime(
                    blockchain=blockchain,
                    retriever=selected_retriever,
                    llm=selected_llm,
                    settings=settings,
                    transactions=transactions,
                )
                if runtime.history_enabled:
                    start_wallet_history(
                        app,
                        runtime,
                        blockchain,
                        selected_retriever,
                        selected_llm,
                        settings,
                        resources,
                    )
            yield

    return lifespan
