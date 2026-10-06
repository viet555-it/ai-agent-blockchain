from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.routes_chat import router as chat_router
from app.api.routes_wallet import router as wallet_router
from app.api.routes_guardrail import router as guardrail_router
from app.api.routes_rag import router as rag_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend API for Web3 AI Agent System with Tool Calling, Guardrails, and RAG"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
app.include_router(chat_router, prefix=settings.API_V1_STR)
app.include_router(wallet_router, prefix=settings.API_V1_STR)
app.include_router(guardrail_router, prefix=settings.API_V1_STR)
app.include_router(rag_router, prefix=settings.API_V1_STR)

@app.get("/")
async def root():
    return {
        "status": "online",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "chain_id": settings.CHAIN_ID,
        "chain_name": settings.CHAIN_NAME,
        "guardrail_active": True,
        "rag_active": True
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
