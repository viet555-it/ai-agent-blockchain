"""Chat API endpoints."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from backend.agent.agent_service import AgentResponse
from backend.api.dependencies import legacy_only
from backend.api.schemas import ChatRequest

logger = logging.getLogger("backend.api")

router = APIRouter()


@router.post("/api/chat", response_model=AgentResponse)
async def handle_chat(request: Request, req: ChatRequest):
    legacy_only(request)
    try:
        wallet = req.wallet_address or request.app.state.demo_wallet
        if request.app.state.read_agent is not None:
            response = await request.app.state.read_agent.process_message(
                req.query, wallet=wallet, session_id=req.session_id
            )
        else:
            response = await asyncio.to_thread(
                request.app.state.agent.process_message, query=req.query, user_wallet=wallet
            )
        return response
    except Exception:
        logger.exception("Error in handle_chat")
        raise HTTPException(
            status_code=503, detail="Agent is unavailable; check local runtime logs."
        ) from None
