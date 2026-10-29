"""AgentService – public API for backend / frontend integration.

Provides both sync and async/streaming interfaces for the agent.
Backend teammates wrap this with FastAPI, WebSocket, etc.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from agent.core import AgentLoop
from agent.memory import ConversationMemory
from config.settings import LLMProviderName, Settings, get_settings
from tools.registry import ToolRegistry, get_registry

logger = logging.getLogger(__name__)


@dataclass
class AgentEvent:
    """A single event emitted by the agent during processing."""

    type: Literal["thought", "tool_call", "tool_result", "confirmation_required", "final", "error"]
    data: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


class AgentService:
    """Public API for interacting with the AI agent.

    Usage::

        service = AgentService.create()
        events = await service.chat("session1", "What is the balance of 0x...?")
        for event in events:
            print(event.type, event.data)
    """

    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        blockchain: Any,
        llm_provider: Any,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._blockchain = blockchain
        self._llm = llm_provider
        self._sessions: dict[str, ConversationMemory] = {}

    @classmethod
    def create(cls, settings: Settings | None = None) -> AgentService:
        """Factory: create AgentService with all dependencies wired up."""
        settings = settings or get_settings()
        registry = get_registry()
        blockchain = _create_blockchain(settings)
        llm = _create_llm(settings)
        return cls(settings=settings, registry=registry, blockchain=blockchain, llm_provider=llm)

    def _get_or_create_session(self, session_id: str) -> ConversationMemory:
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationMemory(
                max_tokens=self._settings.effective_token_budget
            )
        return self._sessions[session_id]

    async def chat(self, session_id: str, message: str, *, retrieval_context: str = "",
                   system_prompt: str | None = None,
                   request_context: dict[str, Any] | None = None) -> list[AgentEvent]:
        """Process a user message and return all events."""
        memory = self._get_or_create_session(session_id)

        loop = AgentLoop(
            llm=self._llm,
            registry=self._registry,
            blockchain=self._blockchain,
            settings=self._settings,
            memory=memory,
            retrieval_context=retrieval_context,
            system_prompt=system_prompt,
            request_context=request_context,
        )

        raw_events = await loop.run(message)
        return [AgentEvent(type=e["type"], data=e["data"]) for e in raw_events]

    async def chat_stream(
        self, session_id: str, message: str
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message and yield events as they happen."""
        # For now, run the full loop and yield events sequentially.
        # Future: true streaming with async generators in the loop.
        events = await self.chat(session_id, message)
        for event in events:
            yield event

    def clear_session(self, session_id: str) -> None:
        """Clear a session's conversation history."""
        self._sessions.pop(session_id, None)

    def restore_session(self, session_id: str, messages: list[dict], observer=None) -> None:
        """Hydrate persisted completed turns without replaying any tool."""
        memory = ConversationMemory(max_tokens=self._settings.effective_token_budget)
        for message in messages:
            memory.add_message(message)
        memory.observer = observer
        self._sessions[session_id] = memory

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())


# ── Factory helpers ──────────────────────────────────────────────────


def _create_blockchain(settings: Settings) -> Any:
    """Create the appropriate BlockchainService."""
    from services.blockchain import Web3BlockchainService

    if not settings.sepolia_rpc_url or settings.sepolia_rpc_url == "https://rpc.sepolia.org":
        # If using default public RPC or no key, still create Web3 service
        pass
    return Web3BlockchainService(
        rpc_url=settings.sepolia_rpc_url,
        private_key=settings.wallet_private_key,
    )


def _create_llm(settings: Settings) -> Any:
    """Create the appropriate LLMProvider based on settings."""
    match settings.llm_provider:
        case LLMProviderName.GEMINI:
            from agent.llm.gemini import GeminiProvider

            if not settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
            return GeminiProvider(api_key=settings.gemini_api_key, model=settings.llm_model)

        case LLMProviderName.ANTHROPIC:
            from agent.llm.anthropic import AnthropicProvider

            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
            return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.llm_model)

        case LLMProviderName.OPENAI:
            from agent.llm.openai_adapter import OpenAIProvider

            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            return OpenAIProvider(api_key=settings.openai_api_key, model=settings.llm_model)

        case LLMProviderName.FAKE:
            from agent.llm.fake import FakeLLMProvider

            return FakeLLMProvider()

        case _:
            raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
