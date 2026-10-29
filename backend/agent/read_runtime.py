"""Orchestrate scoped retrieval, bounded context, agent execution and response mapping."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from agent.service import AgentService
from backend.agent.models import AgentResponse, TimelineStep
from backend.agent.prompts import read_system_prompt
from backend.agent.query_rules import amount_clarification as amount_clarification
from backend.agent.query_rules import normalize_retrieval_query as normalize_retrieval_query
from backend.agent.read_tools import BackendReadRegistry as BackendReadRegistry
from backend.agent.read_tools import BackendReadTool as BackendReadTool
from backend.agent.read_tools import json_value as json_value
from backend.agent.response_mapper import map_agent_response
from backend.agent.retrieval_context import build_retrieval_context
from backend.rag.rag_adapter import RAGSearchResult
from config.settings import Settings
from rag.retriever import InvalidQuery, RetrievalTimeout, RetrievalUnavailable


class ReadAgentRuntime:
    def __init__(
        self,
        *,
        blockchain: Any,
        retriever: Any,
        llm: Any,
        settings: Settings,
        transactions: Any = None,
    ):
        self.blockchain = blockchain
        self.retriever = retriever
        # No key enters the integrated agent, regardless of settings passed by the caller.
        settings = settings.model_copy(update={"dry_run": True, "wallet_private_key": ""})
        self.transactions = transactions
        self.service = AgentService(
            settings, BackendReadRegistry(blockchain, transactions), blockchain, llm
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._settings = settings

    def clear_session(self, session_id: str) -> None:
        """Release memory and the runtime lock after a completed or failed turn."""
        self.service.clear_session(session_id)
        self._locks.pop(session_id, None)

    async def process_message(self, query: str, *, wallet: str, session_id: str) -> AgentResponse:
        if session_id not in self._locks:
            if len(self._locks) >= 100:
                raise RetrievalUnavailable("Maximum local demo sessions reached; restart the demo")
            self._locks[session_id] = asyncio.Lock()
        async with self._locks[session_id]:
            return await self._process(query, wallet, session_id)

    async def _process(self, query: str, wallet: str, session_id: str) -> AgentResponse:
        start = time.perf_counter()
        timeline = [TimelineStep(step_number=1, name="Request received", status="SUCCESS")]
        retrieval_query = normalize_retrieval_query(query)
        try:
            chunks = await self.retriever.retrieve(retrieval_query, k=5)
        except (InvalidQuery, RetrievalTimeout, RetrievalUnavailable) as exc:
            result = RAGSearchResult(
                query=query,
                retrieval_query=retrieval_query,
                provider="scoped_vector_db",
                status=type(exc).__name__,
            )
            return AgentResponse(
                query=query,
                reply="Không thể truy xuất tài liệu; hãy kiểm tra RAG trước khi thử lại.",
                intent="retrieval_error",
                rag_result=result,
                error=type(exc).__name__,
                timeline=timeline,
            )

        scope = self.retriever.scope
        if any(not scope.accepts(chunk["metadata"]) for chunk in chunks):
            raise RetrievalUnavailable("Retriever returned a chunk outside its bound scope")
        memory = self.service.get_session(session_id)
        context, rag = build_retrieval_context(
            query=query,
            retrieval_query=retrieval_query,
            chunks=chunks,
            chain_id=self.blockchain.chain_id,
            wallet=wallet,
            transactions=self.transactions,
            memory=memory,
            token_budget=self._settings.effective_token_budget,
        )
        timeline.append(
            TimelineStep(
                step_number=2,
                name="Scoped RAG retrieval",
                status="SUCCESS",
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                result={
                    "provider": rag.provider,
                    "status": rag.status,
                    "documents": len(rag.documents),
                },
            )
        )
        clarification = amount_clarification(query)
        if clarification:
            memory.add_user(query)
            memory.add_assistant(content=clarification)
            timeline.append(
                TimelineStep(
                    step_number=9,
                    name="Clarification required",
                    status="INFO",
                    result={"missing_field": "amount"},
                )
            )
            return AgentResponse(
                query=query,
                reply=clarification,
                intent="clarification",
                rag_result=rag,
                timeline=timeline,
            )
        prompt = read_system_prompt(
            self.blockchain.chain_id, proposals_enabled=self.transactions is not None
        )
        request_context = {
            "session_id": session_id,
            "wallet": wallet,
            "proposal_results": [],
            "stop_after_proposal": True,
        }
        events = await self.service.chat(
            session_id,
            query,
            retrieval_context=context,
            system_prompt=prompt,
            request_context=request_context,
        )
        return map_agent_response(
            events=events,
            query=query,
            rag=rag,
            request_context=request_context,
            timeline=timeline,
            start=start,
        )
