"""System API endpoints."""

import logging

from fastapi import APIRouter, HTTPException, Request

from backend.api.dependencies import legacy_only
from backend.api.schemas import SwitchNetworkRequest

logger = logging.getLogger("backend.api")

router = APIRouter()


@router.get("/api/health")
def get_health(
    request: Request,
):
    return {
        "status": "healthy",
        "service": "AI Agent Blockchain API",
        "chain_id": request.app.state.network_manager.active_chain_id,
        "active_wallet": request.app.state.demo_wallet,
        "agent_mode": request.app.state.agent_mode,
        "local_writes_enabled": bool(
            request.app.state.local_writes and not request.app.state.history_enabled
        ),
        "wallet_history_enabled": request.app.state.history_enabled,
        "browser_wallet_writes": bool(
            request.app.state.history_enabled and request.app.state.wallet_settings.browser_writes
        ),
    }


@router.get("/api/network/status")
def get_network_status(
    request: Request,
):
    config = request.app.state.network_manager.get_network_config()
    rpcs = config.all_rpc_urls()
    health_list = []
    for rpc in rpcs[:3]:  # Check up to 3 RPCs
        health = request.app.state.network_manager.check_rpc_health(
            rpc, config.chain_id, timeout=2.5
        )
        health_list.append(health.to_dict())

    # Get latest block and gas
    block_info = None
    gas_info = None
    try:
        latest = request.app.state.blockchain.get_block("latest")
        block_info = {
            "number": latest.get("number"),
            "hash": latest.get("hash", {}).hex()
            if hasattr(latest.get("hash"), "hex")
            else str(latest.get("hash")),
        }
        gas_info = request.app.state.blockchain.get_gas_price()
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
        "available_networks": request.app.state.network_manager.list_networks(),
    }


@router.post("/api/network/switch")
def switch_network(request: Request, req: SwitchNetworkRequest):
    if req.chain_id != request.app.state.profile.chain_id:
        raise HTTPException(
            status_code=400, detail="Network switch outside the runtime profile is disabled"
        )
    return {
        "status": "success",
        "chain_id": req.chain_id,
        "network_name": request.app.state.network_manager.get_network_config().name,
    }


@router.get("/api/wallet/info")
def get_wallet_info(request: Request, address: str | None = None):
    target = address or request.app.state.demo_wallet
    config = request.app.state.network_manager.get_network_config()

    native_bal = {"balance": "0.0", "symbol": config.native_currency.symbol}
    token_bal = {"balance": "0.0", "symbol": "AGNT", "token_address": "N/A"}

    try:
        native_bal = request.app.state.blockchain.get_native_balance(target)
    except Exception as e:
        logger.warning(f"Error fetching native balance: {e}")

    try:
        token_addr = config.default_contracts.get("AgentToken")
        if token_addr:
            token_bal = request.app.state.blockchain.get_token_balance(token_addr, target)
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
        "explorer_url": f"{config.block_explorer_url}/address/{target}"
        if config.block_explorer_url
        else None,
    }


@router.get("/api/guardrail/policies")
def get_guardrail_policies(
    request: Request,
):
    return {
        "max_native_transfer_limit": str(
            request.app.state.policy_engine.config.max_native_transfer_limit
        ),
        "max_token_transfer_limit": str(
            request.app.state.policy_engine.config.max_token_transfer_limit
        ),
        "recipient_whitelist": request.app.state.policy_engine.config.recipient_whitelist,
        "enforce_whitelist": request.app.state.policy_engine.config.enforce_whitelist,
        "require_human_approval_for_writes": request.app.state.policy_engine.config.require_human_approval_for_writes,
        "approval_timeout_seconds": request.app.state.policy_engine.config.approval_timeout_seconds,
    }


@router.get("/api/guardrail/audits")
def get_audit_logs(request: Request, limit: int = 30):
    legacy_only(request)
    return request.app.state.policy_engine.list_audit_events(limit=limit)
