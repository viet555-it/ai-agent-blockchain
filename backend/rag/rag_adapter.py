"""RAG (Retrieval-Augmented Generation) Adapter Interface.

Coordinates context retrieval between the AI Agent and the RAG subsystem owned by Nguyễn Trọng Bảo Việt.
Provides clean data models, source citations, and fallback local domain knowledge.
"""
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field


class RetrievedDocument(BaseModel):
    """Represents a chunk of retrieved knowledge context."""
    doc_id: str
    title: str
    source_file: str
    score: float = Field(default=0.9, ge=-1.0, le=1.0, allow_inf_nan=False)
    excerpt: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RAGSearchResult(BaseModel):
    """Result of context retrieval for an agent query."""
    query: str
    retrieval_query: str | None = None
    documents: List[RetrievedDocument] = Field(default_factory=list)
    has_relevant_context: bool = False
    provider: str = "curated_knowledge_adapter"  # Or "vector_db" once integrated by Nguyễn Trọng Bảo Việt
    status: str = "ok"


class RAGAdapter:
    """Pluggable adapter for RAG context retrieval.

    Designed to cleanly integrate with the vector database module developed by team member Nguyễn Trọng Bảo Việt.
    """

    def __init__(self):
        self._custom_retriever: Optional[Callable[[str, int], List[RetrievedDocument]]] = None
        # Default curated project documents based on contracts & blockchain docs
        self._knowledge_base: List[Dict[str, Any]] = [
            {
                "doc_id": "doc-tokenomics-01",
                "title": "AgentToken (AGNT) Tokenomics & Specs",
                "source_file": "contracts/src/AgentToken.sol",
                "keywords": ["token", "agnt", "supply", "cap", "decimals", "tokenomics", "contract"],
                "excerpt": "AgentToken (AGNT) is an ERC-20 Capped token on Ethereum/Sepolia. Maximum total supply is capped at 10,000,000 AGNT with 18 decimals. The initial supply of 1,000,000 AGNT is minted to the deployer.",
                "metadata": {"category": "smart_contract", "network": "Sepolia 11155111"},
            },
            {
                "doc_id": "doc-guardrail-02",
                "title": "Smart Contract Guardrail & Limits",
                "source_file": "contracts/src/AgentToken.sol",
                "keywords": ["guardrail", "limit", "max", "transfer", "protection", "500"],
                "excerpt": "To prevent unauthorized large drains, the smart contract enforces an on-chain maxTransferLimit of 500 AGNT per transaction by default. Any transfer exceeding this reverts with 'AgentToken: Transfer exceeds max limit'.",
                "metadata": {"category": "security_policy"},
            },
            {
                "doc_id": "doc-faucet-03",
                "title": "Testnet Faucet & Cooldown Policy",
                "source_file": "contracts/src/AgentToken.sol",
                "keywords": ["faucet", "claim", "free", "testnet", "cooldown", "100"],
                "excerpt": "Users and the AI Agent can claim up to 100 AGNT test tokens via the faucet() function. To mitigate abuse, a mandatory cooldown period of 1 minute (60s) is enforced per wallet address between claims.",
                "metadata": {"category": "faucet_rules"},
            },
            {
                "doc_id": "doc-network-04",
                "title": "Multi-Network & RPC Failover Specs",
                "source_file": "docs/BLOCKCHAIN_SERVICE.md",
                "keywords": ["network", "rpc", "failover", "sepolia", "hardhat", "chain", "latency"],
                "excerpt": "The backend supports multi-chain operation (Hardhat Localhost 31337 and Ethereum Sepolia 11155111). Automatic RPC failover selects the fastest healthy endpoint and verifies runtime bytecode hashes before executing transactions.",
                "metadata": {"category": "infrastructure"},
            },
            {
                "doc_id": "doc-policy-05",
                "title": "Guardrail Policy Engine: Whitelist & Human Approval",
                "source_file": "backend/guardrail/policy_engine.py",
                "keywords": ["whitelist", "approval", "human", "policy", "security", "tamper", "write"],
                "excerpt": "All state-modifying write operations (ETH transfers, ERC-20 transfers, approves, faucet claims) strictly require recipient whitelist validation and explicit human confirmation. Tampering with parameters during review invalidates the approval token.",
                "metadata": {"category": "guardrail_engine"},
            },
        ]

    def register_provider(self, retriever_fn: Callable[[str, int], List[RetrievedDocument]]):
        """Allows team member Nguyễn Trọng Bảo Việt to plug in his RAG vector database engine."""
        self._custom_retriever = retriever_fn

    def retrieve(self, query: str, top_k: int = 3) -> RAGSearchResult:
        """Retrieve relevant context for a user or agent prompt."""
        if not query or not query.strip():
            return RAGSearchResult(query=query, documents=[], has_relevant_context=False)

        # If custom vector retriever is provided by Nguyễn Trọng Bảo Việt, delegate to it
        if self._custom_retriever:
            try:
                docs = self._custom_retriever(query, top_k)
                return RAGSearchResult(
                    query=query,
                    documents=docs,
                    has_relevant_context=len(docs) > 0,
                    provider="external_vector_db",
                )
            except Exception as e:
                # Log error and fallback to domain knowledge
                pass

        # Fallback keyword matching across project knowledge base
        q_lower = query.lower()
        scored_docs: List[Tuple[float, RetrievedDocument]] = []

        for item in self._knowledge_base:
            score = 0.0
            for kw in item["keywords"]:
                if kw in q_lower:
                    score += 0.25
            if score > 0:
                score = min(score, 0.98)
                doc = RetrievedDocument(
                    doc_id=item["doc_id"],
                    title=item["title"],
                    source_file=item["source_file"],
                    score=round(score, 2),
                    excerpt=item["excerpt"],
                    metadata=item["metadata"],
                )
                scored_docs.append((score, doc))

        # Sort descending by score
        scored_docs.sort(key=lambda x: x[0], reverse=True)
        results = [doc for _, doc in scored_docs[:top_k]]

        return RAGSearchResult(
            query=query,
            documents=results,
            has_relevant_context=len(results) > 0,
            provider="curated_knowledge_adapter",
        )
