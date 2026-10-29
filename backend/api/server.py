"""FastAPI application factory; importing this module never connects to RPC."""
import logging
import asyncio
import hashlib
import json
import os
from contextlib import suppress
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from config.environment import load_project_env

from backend.agent.agent_service import BlockchainAgent
from backend.api.routes import approvals as approval_routes, chat as chat_routes, system as system_routes
# Preserve existing imports while callers migrate to backend.api.schemas.
from backend.api.schemas import (
    ApprovalActionRequest as ApprovalActionRequest,
    ChatRequest as ChatRequest,
    ProposalRequest as ProposalRequest,
    SwitchNetworkRequest as SwitchNetworkRequest,
)
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.network.network_manager import NetworkManager
from backend.rag.rag_adapter import RAGAdapter
from backend.runtime_profiles import RuntimeProfile
from backend.services.blockchain_service import BlockchainService
from backend.services.transaction_coordinator import TransactionCoordinator

REPO_ROOT = Path(__file__).resolve().parents[2]
load_project_env()
logger = logging.getLogger("backend.api")


def create_app(
    *, profile: str | None = None, blockchain: BlockchainService | None = None,
    policy: PolicyEngine | None = None, rag: RAGAdapter | None = None,
    wallet: str | None = None,
    agent_mode: str | None = None, llm: Any = None, retriever: Any = None,
    agent_settings: Any = None,
    enable_local_writes: bool | None = None,
    sepolia_execution: Any = None,
    wallet_settings: Any = None,
) -> FastAPI:
    history_enabled = wallet_settings is not None or (
        profile != "unit" and os.environ.get("WALLET_HISTORY_ENABLED", "false").lower() == "true")
    if history_enabled:
        from backend.wallet_settings import WalletSettings
        wallet_settings = wallet_settings or WalletSettings.from_environment()
    runtime_profile = RuntimeProfile.load(profile, allow_sepolia_write=sepolia_execution is not None)
    if sepolia_execution is not None and (runtime_profile.name != "sepolia_write" or agent_mode != "llm"):
        raise ValueError("Explicit Sepolia execution requires sepolia_write and llm mode")
    network_config = runtime_profile.network()
    network_manager = NetworkManager({runtime_profile.chain_id: network_config})
    network_manager.set_active_chain_id(runtime_profile.chain_id)
    policy_engine = policy or PolicyEngine(PolicyConfig())
    rag_adapter = rag or RAGAdapter()
    blockchain_service = blockchain
    agent = None
    read_agent = None
    transactions = None
    mode = agent_mode or os.environ.get("PHASE3_AGENT", "legacy")
    if mode not in {"legacy", "llm"}:
        raise ValueError("PHASE3_AGENT must be legacy or llm")
    local_writes = enable_local_writes
    if local_writes is None:
        flag = os.environ.get("PHASE3_LOCAL_WRITES", "false").lower()
        if flag not in {"true", "false"}:
            raise ValueError("PHASE3_LOCAL_WRITES must be true or false")
        local_writes = flag == "true"
    if local_writes and (runtime_profile.name != "local_evm" or mode != "llm"):
        raise ValueError("Local writes require local_evm profile and llm agent mode")
    if history_enabled and mode != "llm":
        raise ValueError("Wallet history requires PHASE3_AGENT=llm")
    if history_enabled and sepolia_execution is not None:
        raise ValueError("Browser-wallet history cannot share the legacy Sepolia execution grant")
    DEMO_WALLET = wallet or os.environ.get("DEMO_WALLET_ADDRESS")
    if not DEMO_WALLET:
        if runtime_profile.chain_id == 31337:
            DEMO_WALLET = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
        else:
            _, manifest = network_manager.load_deployment_manifest(runtime_profile.chain_id)
            DEMO_WALLET = manifest["deployer"]
    if local_writes and policy is None:
        policy_engine = PolicyEngine(PolicyConfig(recipient_whitelist=[DEMO_WALLET, *policy_engine.config.recipient_whitelist]))
    if sepolia_execution is not None and policy is None:
        policy_engine = PolicyEngine(PolicyConfig(recipient_whitelist=[sepolia_execution.sender, sepolia_execution.recipient]))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal blockchain_service, agent, read_agent, transactions
        if blockchain_service is None:
            if runtime_profile.name == "unit":
                raise RuntimeError("unit profile requires an injected blockchain service")
            blockchain_service = BlockchainService(
                network_manager=network_manager, chain_id=runtime_profile.chain_id,
            )
        if blockchain_service.chain_id != runtime_profile.chain_id:
            raise ValueError("Injected blockchain service does not match the runtime chain")
        if local_writes and not history_enabled:
            transactions = TransactionCoordinator(blockchain_service, policy_engine, DEMO_WALLET)
            network_config.default_contracts["AgentToken"] = transactions.contract_address
        elif sepolia_execution is not None:
            from backend.services.sepolia_execution import SepoliaTransactionCoordinator
            transactions = SepoliaTransactionCoordinator(blockchain_service, policy_engine, sepolia_execution)
            network_config.default_contracts["AgentToken"] = transactions.contract_address
        app.state.transactions = transactions
        agent = BlockchainAgent(
            blockchain_service=blockchain_service, policy_engine=policy_engine,
            rag_adapter=rag_adapter, default_wallet=DEMO_WALLET,
        )
        app.state.agent = agent
        app.state.blockchain = blockchain_service
        wallet_db = None
        receipt_task = None
        owned_retriever = None
        owned_llm = None
        try:
            if mode == "llm":
                from agent.service import _create_llm
                from backend.agent.read_runtime import ReadAgentRuntime
                from config.settings import Settings
                from rag.models import DeploymentScope
                from rag.retriever import RAGRetriever, SourceScope

                settings = agent_settings or Settings(
                    _env_file=None, llm_provider=os.environ.get("LLM_PROVIDER", "fake"),
                    llm_model=os.environ.get("LLM_MODEL", ""),
                    gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
                    anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
                    openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
                    wallet_private_key="", dry_run=True,
                )
                if llm is None and settings.llm_provider != "fake" and not settings.llm_model:
                    raise ValueError("Set an explicit active LLM_MODEL before enabling a real provider")
                selected_llm = llm if llm is not None else _create_llm(settings)
                if llm is None:
                    owned_llm = selected_llm
                selected_retriever = retriever
                if selected_retriever is None:
                    manifest = json.loads((REPO_ROOT / "knowledge/manifest.json").read_text(encoding="utf-8"))
                    if runtime_profile.chain_id == 31337:
                        versions = {s["doc_version"] for s in manifest["sources"]
                                    if s["scope"] == "source_only" and s["usage"] == "ingest"}
                        if len(versions) != 1:
                            raise ValueError("Select an explicit source version for local retrieval")
                        scope = SourceScope(versions.pop(), include_general=True)
                    else:
                        scope = DeploymentScope(**manifest["deployment_scope"])
                    owned_retriever = await RAGRetriever.create(root=REPO_ROOT, scope=scope)
                    selected_retriever = owned_retriever
                scope = selected_retriever.scope
                if runtime_profile.chain_id == 31337:
                    if not isinstance(scope, SourceScope):
                        raise ValueError("Local LLM runtime requires SourceScope, not a Sepolia deployment")
                else:
                    _, deployment = network_manager.load_deployment_manifest(runtime_profile.chain_id)
                    abi_text = (REPO_ROOT / f"backend/abi/{runtime_profile.chain_id}/AgentToken_abi.json").read_text(encoding="utf-8")
                    abi_hash = "sha256:" + hashlib.sha256(abi_text.encode("utf-8")).hexdigest()
                    if (not isinstance(scope, DeploymentScope) or scope.chain_id != runtime_profile.chain_id
                            or scope.contract_address.lower() != deployment["contractAddress"].lower()
                            or scope.abi_hash != abi_hash):
                        raise ValueError("RAG deployment scope does not match the active chain/contract/ABI")
                read_agent = ReadAgentRuntime(blockchain=blockchain_service, retriever=selected_retriever,
                                             llm=selected_llm, settings=settings, transactions=transactions)
                app.state.read_agent = read_agent
                if history_enabled:
                    from backend.db.store import Database
                    from backend.services.browser_wallet import BrowserWalletService
                    from backend.services.history_service import HistoryService
                    from backend.services.wallet_auth import WalletAuth
                    wallet_db = Database(wallet_settings.database_url)
                    wallet_db.check_schema()
                    app.state.wallet_db = wallet_db
                    app.state.wallet_auth = WalletAuth(wallet_db, wallet_settings, runtime_profile.chain_id, blockchain_service)
                    app.state.history = HistoryService(wallet_db)
                    app.state.history.recover()
                    browser = BrowserWalletService(wallet_db, wallet_settings, blockchain_service, policy_engine)
                    network_config.default_contracts["AgentToken"] = browser.contract_address
                    app.state.browser_wallet = browser
                    app.state.history_runtime = ReadAgentRuntime(blockchain=blockchain_service, retriever=selected_retriever,
                        llm=selected_llm, settings=settings, transactions=browser if wallet_settings.browser_writes else None)

                    async def reconcile():
                        while True:
                            try:
                                await asyncio.to_thread(browser.reconcile_batch)
                                await asyncio.to_thread(app.state.history.recover)
                            except asyncio.CancelledError:
                                raise
                            except HTTPException as error:
                                logger.warning("Wallet receipt reconciliation deferred: %s", error.detail)
                            except Exception:
                                logger.warning("Wallet receipt reconciliation deferred; dependencies unavailable")
                            await asyncio.sleep(15)
                    receipt_task = asyncio.create_task(reconcile())
            yield
        finally:
            if receipt_task:
                receipt_task.cancel()
                with suppress(asyncio.CancelledError):
                    await receipt_task
            if wallet_db:
                wallet_db.close()
            if owned_retriever is not None:
                await owned_retriever.aclose()
            if owned_llm is not None and hasattr(owned_llm, "aclose"):
                await owned_llm.aclose()

    app = FastAPI(title="AI Agent with Blockchain Tools API", version="1.0.0", lifespan=lifespan)
    app.state.profile = runtime_profile
    app.state.policy_engine = policy_engine
    app.state.network_manager = network_manager
    app.state.history_enabled = history_enabled
    app.state.demo_wallet = DEMO_WALLET
    app.state.agent_mode = mode
    app.state.local_writes = local_writes
    app.state.wallet_settings = wallet_settings
    app.state.read_agent = None
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:5173"],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    if history_enabled:
        from backend.api.wallet_routes import router
        app.include_router(router)

        from backend.api.error_handlers import install_wallet_handlers
        install_wallet_handlers(app)

    app.include_router(system_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(approval_routes.router)

    frontend = REPO_ROOT / "frontend"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
    return app


app = create_app()


def run():
    import uvicorn
    uvicorn.run("backend.api.server:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    run()
