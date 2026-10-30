"""FastAPI application factory; importing this module never connects to RPC."""

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.routes import approvals as approval_routes
from backend.api.routes import chat as chat_routes
from backend.api.routes import prices as price_routes
from backend.api.routes import system as system_routes

# Preserve existing imports while callers migrate to backend.api.schemas.
from backend.api.schemas import (
    ApprovalActionRequest as ApprovalActionRequest,
)
from backend.api.schemas import (
    ChatRequest as ChatRequest,
)
from backend.api.schemas import (
    ProposalRequest as ProposalRequest,
)
from backend.api.schemas import (
    SwitchNetworkRequest as SwitchNetworkRequest,
)
from backend.bootstrap.lifespan import build_lifespan
from backend.bootstrap.runtime import resolve_runtime
from backend.guardrail.policy_engine import PolicyEngine
from backend.rag.rag_adapter import RAGAdapter
from backend.services.blockchain_service import BlockchainService
from config.environment import load_project_env

REPO_ROOT = Path(__file__).resolve().parents[2]
load_project_env()


def create_app(
    *,
    profile: str | None = None,
    blockchain: BlockchainService | None = None,
    policy: PolicyEngine | None = None,
    rag: RAGAdapter | None = None,
    wallet: str | None = None,
    agent_mode: str | None = None,
    llm: Any = None,
    retriever: Any = None,
    agent_settings: Any = None,
    enable_local_writes: bool | None = None,
    sepolia_execution: Any = None,
    wallet_settings: Any = None,
) -> FastAPI:
    runtime = resolve_runtime(
        profile=profile,
        policy=policy,
        rag=rag,
        wallet=wallet,
        agent_mode=agent_mode,
        enable_local_writes=enable_local_writes,
        sepolia_execution=sepolia_execution,
        wallet_settings=wallet_settings,
    )
    lifespan = build_lifespan(
        runtime,
        root=REPO_ROOT,
        blockchain=blockchain,
        llm=llm,
        retriever=retriever,
        agent_settings=agent_settings,
    )
    app = FastAPI(title="AI Agent with Blockchain Tools API", version="1.0.0", lifespan=lifespan)
    app.state.profile = runtime.profile
    app.state.policy_engine = runtime.policy
    app.state.network_manager = runtime.network_manager
    app.state.history_enabled = runtime.history_enabled
    app.state.demo_wallet = runtime.wallet
    app.state.agent_mode = runtime.agent_mode
    app.state.local_writes = runtime.local_writes
    app.state.wallet_settings = runtime.wallet_settings
    app.state.read_agent = None
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if runtime.history_enabled:
        from backend.api.wallet_routes import router

        app.include_router(router)

        from backend.api.error_handlers import install_wallet_handlers

        install_wallet_handlers(app)

    app.include_router(system_routes.router)
    app.include_router(chat_routes.router)
    app.include_router(approval_routes.router)
    app.include_router(price_routes.router)

    frontend = REPO_ROOT / "frontend"
    if frontend.exists():
        app.mount("/", StaticFiles(directory=str(frontend), html=True), name="frontend")
    return app


app = create_app()


def run():
    import uvicorn

    uvicorn.run(
        "backend.api.server:app", host="127.0.0.1", port=int(os.environ.get("PORT", "8000"))
    )


if __name__ == "__main__":
    run()
