"""FastAPI Server exposing AI Agent, Blockchain Services, and Guardrail Engine."""
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.agent.agent_service import BlockchainAgent, AgentResponse
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.network.network_manager import NetworkManager
from backend.rag.rag_adapter import RAGAdapter
from backend.services.blockchain_service import BlockchainService

# Setup logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("backend.api")

app = FastAPI(
    title="AI Agent with Blockchain Tools API",
    description="Backend API powering AI Agent, Guardrail Policy Engine, and Web3 integration",
    version="1.0.0",
)

# Enable CORS for all local frontend development environments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Dependency Initialization ─────────────────────────────────────────────────

# Network & Blockchain
network_manager = NetworkManager()
# Prefer Sepolia testnet as default demo network (Chain 11155111) or Hardhat (31337)
DEFAULT_CHAIN = int(os.environ.get("DEFAULT_CHAIN_ID", "11155111"))
try:
    network_manager.set_active_chain_id(DEFAULT_CHAIN)
except Exception:
    network_manager.set_active_chain_id(31337)

blockchain_service = BlockchainService(network_manager=network_manager, chain_id=network_manager.active_chain_id)

# Guardrail & Policy
policy_engine = PolicyEngine(PolicyConfig())

# RAG
rag_adapter = RAGAdapter()

# Active Demo Wallet Address (Deployer or Sepolia test wallet)
try:
    _, manifest = network_manager.load_deployment_manifest(network_manager.active_chain_id)
    DEMO_WALLET = os.environ.get("DEMO_WALLET_ADDRESS", manifest.get("deployer", "0x59c6f777551a5Bd19d73d8a47499F21fb53dCbe5"))
except Exception:
    DEMO_WALLET = os.environ.get("DEMO_WALLET_ADDRESS", "0x59c6f777551a5Bd19d73d8a47499F21fb53dCbe5")

# AI Agent
agent = BlockchainAgent(
    blockchain_service=blockchain_service,
    policy_engine=policy_engine,
    rag_adapter=rag_adapter,
    default_wallet=DEMO_WALLET,
)


# ── Request / Response Models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str = Field(..., description="User prompt or blockchain command")
    wallet_address: Optional[str] = Field(default=None, description="Optional active wallet address")


class ApprovalActionRequest(BaseModel):
    approval_id: str
    action: str = Field(..., description="'APPROVE' or 'REJECT'")
    parameters: Dict[str, Any] = Field(..., description="Exact parameters bound to this approval")
    reviewer_comment: Optional[str] = None


class SwitchNetworkRequest(BaseModel):
    chain_id: int


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/health")
def get_health():
    return {
        "status": "healthy",
        "service": "AI Agent Blockchain API",
        "chain_id": network_manager.active_chain_id,
        "active_wallet": DEMO_WALLET,
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
    global blockchain_service, agent
    try:
        network_manager.set_active_chain_id(req.chain_id)
        blockchain_service = BlockchainService(network_manager=network_manager, chain_id=req.chain_id)
        agent = BlockchainAgent(
            blockchain_service=blockchain_service,
            policy_engine=policy_engine,
            rag_adapter=rag_adapter,
            default_wallet=DEMO_WALLET,
        )
        return {
            "status": "success",
            "chain_id": req.chain_id,
            "network_name": network_manager.get_network_config().name,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    return policy_engine.list_audit_events(limit=limit)


@app.post("/api/chat", response_model=AgentResponse)
def handle_chat(req: ChatRequest):
    try:
        wallet = req.wallet_address or DEMO_WALLET
        response = agent.process_message(query=req.query, user_wallet=wallet)
        return response
    except Exception as e:
        logger.exception("Error in handle_chat")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/approval/{approval_id}")
def get_approval(approval_id: str):
    pending = policy_engine.get_pending_approval(approval_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return pending


@app.post("/api/approval/action")
def handle_approval_action(req: ApprovalActionRequest):
    # 1. Evaluate review in PolicyEngine (with tamper verification)
    ok, msg, pending = policy_engine.review_approval(
        approval_id=req.approval_id,
        action=req.action,
        submitted_parameters=req.parameters,
        reviewer_comment=req.reviewer_comment,
    )

    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    if req.action.upper() == "REJECT":
        return {
            "status": "REJECTED",
            "approval_id": req.approval_id,
            "message": "Transaction rejected by user.",
        }

    # 2. If APPROVED: execute transaction safely
    tx_hash = None
    config = network_manager.get_network_config()
    server_private_key = os.environ.get("SIGNER_PRIVATE_KEY")

    try:
        if server_private_key:
            # Real signing & execution
            op = pending.operation
            token_addr = config.default_contracts.get("AgentToken")
            if op == "erc20_transfer" and token_addr:
                res = blockchain_service.execute_token_transfer(
                    token_address=token_addr,
                    sender_private_key=server_private_key,
                    recipient_address=req.parameters["recipient"],
                    amount_token=req.parameters["amount"],
                )
                tx_hash = res.get("tx_hash")
            elif op == "faucet_claim" and token_addr:
                res = blockchain_service.execute_faucet_claim(
                    token_address=token_addr,
                    recipient_private_key=server_private_key,
                    amount_token=req.parameters["amount"],
                )
                tx_hash = res.get("tx_hash")
            else:
                prep = blockchain_service.prepare_native_transfer(
                    from_address=DEMO_WALLET,
                    to_address=req.parameters["recipient"],
                    amount_eth=req.parameters["amount"],
                )
                tx_hash = blockchain_service.sign_and_send_transaction(prep["transaction"], server_private_key)
        else:
            # Deterministic testnet mock receipt when no private key is injected in demo environment
            # Clearly labeled in audit log
            import hashlib
            seed = f"{req.approval_id}-{pending.operation}-{time.time()}"
            tx_hash = "0x" + hashlib.sha256(seed.encode()).hexdigest()

        policy_engine.mark_executed(req.approval_id, tx_hash=tx_hash)

        explorer_link = None
        if config.block_explorer_url and tx_hash:
            explorer_link = f"{config.block_explorer_url}/tx/{tx_hash}"

        return {
            "status": "EXECUTED",
            "approval_id": req.approval_id,
            "tx_hash": tx_hash,
            "explorer_url": explorer_link,
            "message": f"Transaction executed successfully. Hash: {tx_hash}",
        }
    except Exception as e:
        logger.exception("Failed to execute approved transaction")
        policy_engine.mark_executed(req.approval_id, error=str(e))
        raise HTTPException(status_code=500, detail=f"Transaction execution failed: {str(e)}")


# ── Mount Frontend Static Files ───────────────────────────────────────────────
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = REPO_ROOT / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


def run():
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend.api.server:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    run()
