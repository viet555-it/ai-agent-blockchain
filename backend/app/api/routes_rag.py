from fastapi import APIRouter, Query
from app.services.rag import rag_service

router = APIRouter(prefix="/rag", tags=["RAG Knowledge Base"])

@router.get("/docs")
async def get_all_documents():
    return {
        "count": len(rag_service.get_all_documents()),
        "documents": rag_service.get_all_documents()
    }

@router.get("/query")
async def query_knowledge_base(q: str = Query(..., description="Query terms to search knowledge base")):
    results = rag_service.retrieve(q, top_k=3)
    return {
        "query": q,
        "results": results
    }

