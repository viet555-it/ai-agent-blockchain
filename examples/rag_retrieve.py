"""Run with .venv/Scripts/python.exe -m examples.rag_retrieve from repository root."""

import asyncio
import json
from pathlib import Path

from rag.retriever import RAGRetriever


async def main():
    # Load once and reuse for successive queries in the same scope/event loop.
    async with await RAGRetriever.create(root=Path(__file__).resolve().parents[1]) as retriever:
        chunks = await retriever.retrieve("transfer(address,uint256)", k=3)
        print(json.dumps(chunks, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(main())
