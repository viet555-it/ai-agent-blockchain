"""FastAPI application factory; importing this module never connects to RPC."""
import logging
import asyncio
import hashlib
import json
import uuid
import os
from contextlib import suppress
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, Optional, Literal

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict
from config.environment import load_project_env

from backend.agent.agent_service import BlockchainAgent, AgentResponse
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.network.network_manager import NetworkManager
from backend.rag.rag_adapter import RAGAdapter
from backend.runtime_profiles import RuntimeProfile
from backend.services.blockchain_service import BlockchainService
from backend.services.transaction_coordinator import TransactionCoordinator, TransactionError

REPO_ROOT = Path(__file__).resolve().parents[2]
load_project_env()
logger = logging.getLogger("backend.api")


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="User prompt or blockchain command")
    wallet_address: Optional[str] = Field(default=None, description="Optional active wallet address")
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=128)


class ApprovalActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str
    action: Literal["APPROVE", "REJECT"]
    parameters: Dict[str, Any] = Field(..., description="Exact parameters bound to this approval")
    reviewer_comment: Optional[str] = None
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["native_transfer", "erc20_transfer", "faucet_claim"]
    amount: str
    recipient: str | None = None
    token_address: str | None = None
    wallet_address: str | None = None
    session_id: str = Field(min_length=1, max_length=128)


class SwitchNetworkRequest(BaseModel):
    chain_id: int



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
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:5173"],
        allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
    )
    if history_enabled:
        from backend.api.wallet_routes import router
        from sqlalchemy.exc import SQLAlchemyError
        from fastapi.responses import JSONResponse
        app.include_router(router)

        @app.middleware("http")
        async def private_wallet_responses(request, call_next):
            request_id = uuid.uuid4().hex
            try:
                response = await call_next(request)
            except Exception as error:
                logger.warning("Wallet API request %s failed (%s)", request_id, type(error).__name__)
                response = JSONResponse(status_code=503, content={"detail": {"code": "DEPENDENCY_UNAVAILABLE", "message": "A required service is unavailable. Check the existing request before retrying.", "request_id": request_id}})
            if request.url.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
                response.headers["X-Request-ID"] = request_id
            elif request.url.path in {"/", "/index.html"} or request.url.path.endswith((".js", ".css", ".json")):
                response.headers["Cache-Control"] = "no-cache"
            return response

        @app.exception_handler(SQLAlchemyError)
        async def storage_unavailable(request, error):
            return JSONResponse(status_code=503, content={"detail": {"code": "STORAGE_UNAVAILABLE", "message": "Storage is unavailable. Check the existing request before retrying."}})

        @app.exception_handler(TransactionError)
        async def transaction_unavailable(request, error):
            return JSONResponse(status_code=error.status_code, content={"detail": {"code": "TRANSACTION", "message": str(error)}})

    def legacy_only():
        if history_enabled:
            raise HTTPException(status_code=403, detail="Legacy demo endpoints are disabled in wallet-history mode")

    @app.get("/api/health")
    def get_health():
        return {
            "status": "healthy",
            "service": "AI Agent Blockchain API",
            "chain_id": network_manager.active_chain_id,
            "active_wallet": DEMO_WALLET,
            "agent_mode": mode,
            "local_writes_enabled": bool(local_writes and not history_enabled),
            "wallet_history_enabled": history_enabled,
            "browser_wallet_writes": bool(history_enabled and wallet_settings.browser_writes),
        }


    @app.get("/api/network/status")
    def get_network_status():
        config = network_manager.get_network_config()
        rpcs = config.all_rpc_urls()
        health_list = []
        for rpc in rpcs[:3]:  # Check up to 3 RPCs
            health = network_manager.check_rpc_health(rpc, config.chain_id, timeout=2.5)
            health_list.append(health.to_dict())

        # Get latest block and gas
        block_info = None
        gas_info = None
        try:
            latest = blockchain_service.get_block("latest")
            block_info = {
                "number": latest.get("number"),
                "hash": latest.get("hash", {}).hex() if hasattr(latest.get("hash"), "hex") else str(latest.get("hash")),
            }
            gas_info = blockchain_service.get_gas_price()
        except Exception as e:
            logger.warning(f"Failed to fetch block/gas info: {e}")

        # Smart contract info
        token_address = config.default_contracts.get("AgentToken")

        return {
            "chain_id": config.chain_id,
            "name": config.name,
            "is_testnet": config.is_testnet,
            "native_currency": config.native_currency.model_dump(),
            "block_explorer_url": config.block_explorer_url,
            "contract_address": token_address,
            "rpc_health": health_list,
            "block_info": block_info,
            "gas_info": gas_info,
            "available_networks": network_manager.list_networks(),
        }


    @app.post("/api/network/switch")
    def switch_network(req: SwitchNetworkRequest):
        if req.chain_id != runtime_profile.chain_id:
            raise HTTPException(status_code=400, detail="Network switch outside the runtime profile is disabled")
        return {"status": "success", "chain_id": req.chain_id,
                "network_name": network_manager.get_network_config().name}


    @app.get("/api/wallet/info")
    def get_wallet_info(address: Optional[str] = None):
        target = address or DEMO_WALLET
        config = network_manager.get_network_config()

        native_bal = {"balance": "0.0", "symbol": config.native_currency.symbol}
        token_bal = {"balance": "0.0", "symbol": "AGNT", "token_address": "N/A"}

        try:
            native_bal = blockchain_service.get_native_balance(target)
        except Exception as e:
            logger.warning(f"Error fetching native balance: {e}")

        try:
            token_addr = config.default_contracts.get("AgentToken")
            if token_addr:
                token_bal = blockchain_service.get_token_balance(token_addr, target)
        except Exception as e:
            logger.warning(f"Error fetching token balance: {e}")

        return {
            "address": target,
            "chain_id": config.chain_id,
            "network": config.name,
            "native_balance": native_bal.get("balance"),
            "native_symbol": native_bal.get("symbol"),
            "token_balance": token_bal.get("balance"),
            "token_symbol": token_bal.get("symbol"),
            "token_address": token_bal.get("token_address"),
            "explorer_url": f"{config.block_explorer_url}/address/{target}" if config.block_explorer_url else None,
        }


    @app.get("/api/guardrail/policies")
    def get_guardrail_policies():
        return {
            "max_native_transfer_limit": str(policy_engine.config.max_native_transfer_limit),
            "max_token_transfer_limit": str(policy_engine.config.max_token_transfer_limit),
            "recipient_whitelist": policy_engine.config.recipient_whitelist,
            "enforce_whitelist": policy_engine.config.enforce_whitelist,
            "require_human_approval_for_writes": policy_engine.config.require_human_approval_for_writes,
            "approval_timeout_seconds": policy_engine.config.approval_timeout_seconds,
        }


    @app.get("/api/guardrail/audits")
    def get_audit_logs(limit: int = 30):
        legacy_only()
        return policy_engine.list_audit_events(limit=limit)


    @app.post("/api/chat", response_model=AgentResponse)
    async def handle_chat(req: ChatRequest):
        legacy_only()
        try:
            wallet = req.wallet_address or DEMO_WALLET
            if read_agent is not None:
                response = await read_agent.process_message(req.query, wallet=wallet, session_id=req.session_id)
            else:
                response = await asyncio.to_thread(agent.process_message, query=req.query, user_wallet=wallet)
            return response
        except Exception:
            logger.exception("Error in handle_chat")
            raise HTTPException(status_code=503, detail="Agent is unavailable; check local runtime logs.")


    @app.get("/api/approval/{approval_id}")
    def get_approval(approval_id: str, session_id: str | None = Header(default=None, alias="X-Session-ID")):
        legacy_only()
        if transactions is not None:
            try:
                return transactions.get(approval_id, session_id or "")
            except TransactionError as error:
                raise HTTPException(status_code=error.status_code, detail=str(error)) from None
        pending = policy_engine.get_pending_approval(approval_id)
        if not pending:
            raise HTTPException(status_code=404, detail="Approval request not found")
        return pending


    @app.post("/api/approval/action")
    async def handle_approval_action(req: ApprovalActionRequest):
        legacy_only()
        if transactions is not None:
            try:
                return await asyncio.to_thread(transactions.review, req.approval_id,
                    session_id=req.session_id or "", action=req.action, parameters=req.parameters,
                    comment=req.reviewer_comment)
            except TransactionError as error:
                raise HTTPException(status_code=error.status_code, detail=str(error)) from None
        if req.action.upper() != "REJECT":
            # G3.0 may prepare proposals, but never signs or fabricates an execution.
            raise HTTPException(status_code=403, detail="Execution is disabled in this integration profile; G3.2 is required")
        ok, msg, pending = policy_engine.review_approval(
            approval_id=req.approval_id, action=req.action,
            submitted_parameters=req.parameters, reviewer_comment=req.reviewer_comment,
        )
        if not ok:
            raise HTTPException(status_code=400, detail=msg)
        return {"status": "REJECTED", "approval_id": req.approval_id,
                "message": "Transaction rejected by user."}

    @app.post("/api/transactions/propose")
    async def propose_transaction(req: ProposalRequest):
        legacy_only()
        if transactions is None:
            raise HTTPException(status_code=403, detail="Local transaction mode is disabled")
        try:
            return await asyncio.to_thread(transactions.propose, req.operation, amount=req.amount,
                session_id=req.session_id, recipient=req.recipient, token_address=req.token_address,
                actor_wallet=req.wallet_address)
        except TransactionError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from None
        except Exception:
            raise HTTPException(status_code=503, detail="Local transaction preparation unavailable") from None

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
