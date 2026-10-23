"""Real Chroma scope/ranking tests with deterministic vectors, not quality evidence."""

import asyncio
import json
import sys
from dataclasses import replace

from rag.chunking import PreparedChunk
from rag.index import IndexStore, fingerprint
from rag.loaders import content_hash
from rag.models import DeploymentScope
from rag.retriever import RAGRetriever, RetrievalOptions, RetrievalUnavailable, SourceScope

ADDRESS = "0x" + "a" * 40
ABI_HASH = "sha256:" + "a" * 64
SCOPE = DeploymentScope(11155111, ADDRESS, ABI_HASH, "v1")


class TestProvider:
    @property
    def identity(self):
        return dict(model_id="test/fake", revision="a" * 40, dimension=3, max_tokens=256,
                    normalize_embeddings=True)

    def count_tokens(self, text):
        return len(text.split()) + 2

    def embed(self, texts):
        return [[-1.0, 0.0, 0.0] if text == "outside" else [1.0, 0.0, 0.0] for text in texts]


def chunk(doc_id, body, *, scope="deployed_contract", signature=None, **changes):
    metadata = dict(
        chunk_id=doc_id, doc_id=doc_id, title=doc_id, category="contract_abi", usage="ingest",
        source_path=f"{doc_id}.md", source_origin="workspace", source_commit=None,
        content_hash=content_hash(body), chunk_hash=content_hash(body), parent_id=doc_id,
        scope=scope, doc_version="v1", verification_status="repository_only",
        chain_id=11155111, contract_address=ADDRESS.upper().replace("0X", "0x"), abi_hash=ABI_HASH,
        budget_unit="tokens", measured_length=10, tokenizer_id="test/fake@" + "a" * 40,
    )
    if signature:
        metadata["function_signature"] = signature
    metadata.update(changes)
    return PreparedChunk(body, metadata)


async def run(path):
    store, provider = IndexStore(path), TestProvider()
    transfer_body = "transfer(address,uint256) accepts address and raw token value"
    rows = [
        chunk("transfer", transfer_body, signature="transfer(address,uint256)"),
        chunk("transfer-duplicate", transfer_body, signature="transfer(address,uint256)"),
        chunk("transferFrom", "transferFrom(address,address,uint256) spender allowance", signature="transferFrom(address,address,uint256)"),
        chunk("cap", "cap() getter", signature="cap()"),
        chunk("wrong-chain", "wrong chain", signature="transfer(address,uint256)", chain_id=1),
        chunk("wrong-address", "wrong address", signature="transfer(address,uint256)", contract_address="0x" + "b" * 40),
        chunk("wrong-version", "wrong version", signature="transfer(address,uint256)", doc_version="v2"),
        chunk("source", "Source transfer rule only", scope="source_only", doc_version="source-v1", signature="transfer(address,uint256)"),
        chunk("policy", "Unapproved policy", scope="policy_snapshot", policy_version="policy-v1"),
        chunk("web3", "General Web3 units", scope="general", category="web3"),
        chunk("general-policy", "Not an allowed general category", scope="general", category="policy"),
        chunk("aaa-seed", "Relevant section seed", scope="general", category="web3", parent_id="context-parent"),
        chunk("aaa-sibling", "Lower similarity continuation", scope="general", category="web3", parent_id="context-parent"),
        chunk("aaa-wrong-scope", "Scope cannot be expanded", scope="source_only", doc_version="source-v1", parent_id="context-parent"),
    ]
    rows.extend(chunk(f"general-part-{n}", f"General units part {n}", scope="general",
                      category="web3", parent_id="same-parent") for n in range(3))
    # Build storage with explicit vectors so the wrong-scope records are nearest.
    class StoredProvider(TestProvider):
        def embed(self, texts):
            return [[0.8, 0.6, 0.0] if text == transfer_body else
                    ([0.6, 0.8, 0.0] if text == "Lower similarity continuation" else [1.0, 0.0, 0.0]) for text in texts]
    store.build(rows, StoredProvider(), corpus_hash="test", source_manifest_hash="test")
    options = RetrievalOptions(min_similarity=0.7)
    retriever = RAGRetriever(provider, store, SCOPE, options=options)
    source = RAGRetriever(provider, store, SourceScope("source-v1"), options=options)
    old = RAGRetriever(provider, store, replace(SCOPE, contract_address="0x" + "d" * 40), options=options)
    tiny = RAGRetriever(provider, store, SCOPE, options=replace(options, context_max_tokens=1))
    stale = RAGRetriever(provider, store, SCOPE, options=options, expected_manifest_hash="different")
    strict = RAGRetriever(provider, store, SCOPE, options=replace(options, min_similarity=0.99))
    expanded = RAGRetriever(provider, store, SCOPE, options=replace(options, parent_context=True))
    expanded_tiny = RAGRetriever(provider, store, SCOPE, options=replace(options, parent_context=True, context_max_tokens=1))
    try:
        result = await retriever.retrieve("transfer(address,uint256)")
        assert len(result) == 1  # duplicate body is removed
        assert result[0]["metadata"]["function_signature"] == "transfer(address,uint256)"
        assert abs(result[0]["score"] - 0.8) < 0.0001  # no artificial exact-match score=1
        assert result[0]["metadata"]["threshold_applied"] is False
        assert result[0]["metadata"]["source_commit"] is None
        assert (await strict.retrieve("transfer(address,uint256)"))[0]["score"] < 0.99
        assert await retriever.retrieve("transfer(bytes32,uint256)") == []
        assert await retriever.retrieve("outside") == []
        ordinary = await retriever.retrieve("general information", k=10)
        assert ordinary and all(SCOPE.accepts(c["metadata"]) for c in ordinary)
        assert all(c["metadata"]["doc_id"] != "general-policy" for c in ordinary)
        assert sum(c["metadata"]["parent_id"] == "same-parent" for c in ordinary) == 2
        assert all(c["metadata"]["chunk_id"] != "aaa-sibling" for c in ordinary)
        expanded_result = await expanded.retrieve("general information", k=10)
        sibling = next(c for c in expanded_result if c["metadata"]["chunk_id"] == "aaa-sibling")
        assert abs(sibling["score"] - .6) < .0001
        assert sibling["metadata"]["selection_reason"] == "parent_context"
        assert sibling["metadata"]["threshold_applied"] is False
        assert all(SCOPE.accepts(c["metadata"]) for c in expanded_result)
        assert all(c["metadata"]["chunk_id"] != "aaa-wrong-scope" for c in expanded_result)
        assert await expanded.retrieve("outside") == []
        assert await expanded_tiny.retrieve("general information") == []
        assert await tiny.retrieve("transfer(address,uint256)") == []
        source_result = await source.retrieve("transfer(address,uint256)")
        assert source_result and all(c["metadata"]["scope"] == "source_only" for c in source_result)
        assert any(c["metadata"]["scope"] == "source_only" for c in await source.retrieve("explain supply cap"))
        assert await source.retrieve("cap") == []
        assert await old.retrieve("transfer(address,uint256)") == []
        assert await old.retrieve("transfer") == []
        try:
            await stale.retrieve("general information")
            raise AssertionError("Expected stale manifest error")
        except RetrievalUnavailable:
            pass
        # Corrupt the body without updating provenance. A fresh catalog still
        # passes metadata checks, but candidate content must not be returned.
        store.collection().update(
            ids=["transfer", "transfer-duplicate"], documents=["tampered", "tampered"],
            embeddings=[[0.8, 0.6, 0.0], [0.8, 0.6, 0.0]],
        )
        try:
            await retriever.retrieve("transfer(address,uint256)")
            raise AssertionError("Expected content integrity error")
        except RetrievalUnavailable:
            pass
        return dict(scope_isolation=True, exact_signature=True, true_cosine=True, dedup=True,
                    context_budget=True, parent_context=True, no_match=True, source_mode=True, stale_and_corrupt_errors=True)
    finally:
        for item in (retriever, source, old, tiny, stale, strict, expanded, expanded_tiny):
            await item.aclose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run(sys.argv[1]))))
