from fastapi import APIRouter, HTTPException, Depends
from app.models.schemas import ChatRequest, ChatResponse
from app.agent.engine import AgentEngine

router = APIRouter(prefix="/chat", tags=["Agent Chat"])

@router.post("", response_model=ChatResponse)
async def chat_with_agent(req: ChatRequest):
    """
    Send natural language prompt to Web3 AI Agent.
    Agent processes intent, calls on-chain tools, and returns response + potential transaction action.
    """
    try:
        engine = AgentEngine(chain_id=req.chain_id)
        response = await engine.process_chat(
            message=req.message,
            wallet_address=req.wallet_address,
            conversation_history=req.conversation_history,
            custom_api_key=req.api_key
        )
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

