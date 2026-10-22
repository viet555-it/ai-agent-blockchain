"""Retriever interface for RAG integration.

Teammate responsible for RAG (FAISS / ChromaDB) implements ``Retriever``.
Default is ``NullRetriever`` which always returns an empty list so the
agent loop works without RAG.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class Chunk(TypedDict):
    """A single retrieval result."""

    content: str
    metadata: dict[str, Any]
    score: float


@runtime_checkable
class Retriever(Protocol):
    """Interface for retrieval-augmented generation.

    ``retrieve(query, k)`` returns the top-k most relevant chunks.
    Teammate can provide a real implementation (FAISS, ChromaDB, etc.).
    """

    async def retrieve(self, query: str, k: int = 5) -> list[Chunk]: ...


class NullRetriever:
    """Default no-op retriever – always returns an empty list.

    The agent loop calls this when RAG is disabled (default). Teammate can
    replace it via dependency injection without modifying agent code.
    """

    async def retrieve(self, query: str, k: int = 5) -> list[Chunk]:
        return []
