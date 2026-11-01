"""Chat API endpoints."""

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Request

from backend.agent.models import AgentResponse
from backend.api.schemas import ChatRequest

logger = logging.getLogger("backend.api")

router = APIRouter()


@router.post("/api/chat", response_model=AgentResponse)
async def handle_chat(request: Request, req: ChatRequest):
    """Handle guest chats and read-only AI interactions.

    Authenticated wallet sessions must use /api/history/conversations/{id}/turns.
    """
    if request.app.state.history_enabled and request.cookies.get("ati_session"):
        raise HTTPException(
            status_code=403,
            detail="Legacy demo endpoints are disabled in wallet-history mode",
        )
    try:
        wallet = req.wallet_address or request.app.state.demo_wallet
        lang = req.language or "auto"
        if request.app.state.read_agent is not None:
            response = await request.app.state.read_agent.process_message(
                req.query, wallet=wallet, session_id=req.session_id, language=lang
            )
        else:
            response = await asyncio.to_thread(
                request.app.state.agent.process_message,
                query=req.query,
                user_wallet=wallet,
                language=lang,
            )
        return response
    except Exception:
        logger.exception("Error in handle_chat")
        raise HTTPException(
            status_code=503, detail="Agent is unavailable; check local runtime logs."
        ) from None
