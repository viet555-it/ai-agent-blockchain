"""Scope-bound synchronous candidate search, ranking and context selection."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from rag.index import IndexStore
from rag.loaders import content_hash
from rag.models import Chunk, DeploymentScope

from .candidates import cosine_similarity, embedding_candidates
from .contracts import InvalidQuery, RetrievalOptions, RetrievalUnavailable, SourceScope
from .metadata import restore_metadata, stored_signatures
from .signatures import explicit_signatures


def search(
    query: str,
    k: int,
    *,
    provider: Any,
    store: IndexStore,
    scope: DeploymentScope | SourceScope,
    options: RetrievalOptions,
    expected_manifest_hash: str | None,
    config_hash: str,
    get_catalog: Callable[[Any, dict[str, Any]], dict[str, dict[str, Any]]],
) -> list[Chunk]:
    if provider.count_tokens(query) > provider.identity["max_tokens"]:
        raise InvalidQuery(
            "query exceeds the encoder token limit; shorten it instead of truncating"
        )
    record = store.active(expected_embedding=provider.identity)
    if record is None:
        raise RetrievalUnavailable("No active index")
    if record.get("distance_metric") != "cosine":
        raise RetrievalUnavailable("Retriever requires a cosine index")
    if expected_manifest_hash and record["source_manifest_hash"] != expected_manifest_hash:
        raise RetrievalUnavailable(
            "Index manifest changed; recreate the retriever for the new corpus"
        )
    # Capture one generation for the whole request, even if a writer switches active.json.
    collection = store.client.get_collection(record["collection"], embedding_function=None)
    configuration = collection.configuration
    if (
        not isinstance(configuration, dict)
        or (configuration.get("hnsw") or {}).get("space") != "cosine"
    ):
        raise RetrievalUnavailable("Collection configuration is not cosine HNSW")
    catalog = get_catalog(collection, record)
    allowed = {
        key: meta
        for key, meta in catalog.items()
        if scope.accepts(meta)
        and (meta["scope"] != "general" or meta["category"] in options.general_categories)
    }
    if not allowed:
        return []
    requested = explicit_signatures(query)
    signatures = {key: stored_signatures(meta) for key, meta in catalog.items()}
    global_names = {sig.split("(", 1)[0] for items in signatures.values() for sig in items}
    named = {
        name
        for name in global_names
        if re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", query)
    }
    allowed_signatures = set().union(*(signatures[key] for key in allowed))
    if requested and not requested.issubset(allowed_signatures):
        return []  # An unsupported overload/deployment must not fall back to unrelated general docs.
    exact_ids = (
        {key for key in allowed if signatures[key] & requested}
        if requested
        else {
            key for key in allowed if any(sig.split("(", 1)[0] in named for sig in signatures[key])
        }
    )
    # Source prose can explain a getter (e.g. supply cap) without having a
    # section named cap(). Deployment queries must not borrow another scope's
    # interface merely because the identifier exists elsewhere in the index.
    if (
        named
        and not exact_ids
        and (
            isinstance(scope, DeploymentScope)
            or not any(meta["scope"] == "source_only" for meta in allowed.values())
        )
    ):
        return []
    direct_symbol = bool(named and re.fullmatch(r"`?[A-Za-z_$][\w$]*`?", query))
    if direct_symbol and not exact_ids:
        return []
    vector = provider.embed([query])[0]
    candidates: dict[str, tuple[str, dict[str, Any], float, bool]] = {}
    if requested or direct_symbol:
        # A syntactically exact interface lookup can succeed even when prose
        # similarity is low; the returned score remains the true cosine value.
        candidates.update(embedding_candidates(collection, exact_ids, vector, direct=True))
    else:
        result = collection.query(
            query_embeddings=[vector],
            ids=sorted(allowed),
            n_results=min(len(allowed), max(options.candidate_pool, k * 4)),
            include=["documents", "metadatas", "distances"],
        )
        for row_id, text, flat, distance in zip(
            result["ids"][0],
            result["documents"][0],
            result["metadatas"][0],
            result["distances"][0],
            strict=True,
        ):
            candidates[row_id] = (
                text,
                restore_metadata(row_id, flat),
                cosine_similarity(float(distance)),
                False,
            )
        # Include named candidates outside ANN top-N, still subject to the prose threshold.
        missing = exact_ids - candidates.keys()
        if missing:
            candidates.update(embedding_candidates(collection, missing, vector, direct=False))
    ranked = sorted(
        candidates.items(), key=lambda item: (item[0] not in exact_ids, -item[1][2], item[0])
    )
    # A relevant fragment may refer to another fragment of the same section.
    # Keep the actual cosine score; eligibility comes from an accepted seed,
    # not from pretending that a low-similarity continuation met the cutoff.
    context_ids: set[str] = set()
    if options.parent_context:
        seed_parents = []
        for _row_id, (_, meta, score, direct) in ranked:
            if (direct or score >= options.min_similarity) and meta[
                "parent_id"
            ] not in seed_parents:
                seed_parents.append(meta["parent_id"])
        siblings = {
            i for i, meta in allowed.items() if meta["parent_id"] in seed_parents
        } - candidates.keys()
        if siblings:
            candidates.update(embedding_candidates(collection, siblings, vector, direct=False))
        ranked = []
        for parent in seed_parents:
            items = [
                (i, value) for i, value in candidates.items() if value[1]["parent_id"] == parent
            ]
            items.sort(key=lambda item: (-item[1][2], item[0]))
            ranked.extend(items)
            context_ids.update(
                i
                for i, (_, _, score, direct) in items
                if not direct and score < options.min_similarity
            )
    output: list[Chunk] = []
    seen: set[str] = set()
    parents: dict[str, int] = {}
    for row_id, (text, meta, score, direct) in ranked:
        if row_id not in allowed or not scope.accepts(meta):
            raise RetrievalUnavailable("Candidate escaped the bound scope")
        if not isinstance(text, str) or content_hash(text) != meta["chunk_hash"]:
            raise RetrievalUnavailable("Candidate content hash mismatch")
        if not direct and row_id not in context_ids and score < options.min_similarity:
            continue
        key = meta["chunk_hash"]
        parent = meta["parent_id"]
        if key in seen or parents.get(parent, 0) >= options.max_per_parent:
            continue
        joined = "\n\n".join([chunk["content"] for chunk in output] + [text])
        if provider.count_tokens(joined) > options.context_max_tokens:
            continue
        metadata = copy.deepcopy(meta)
        metadata.update(
            score_metric="cosine_similarity",
            cosine_distance=1.0 - score,
            selection_reason="parent_context"
            if row_id in context_ids
            else (
                "exact_signature"
                if requested
                else ("symbol_name" if row_id in exact_ids else "semantic")
            ),
            threshold_applied=not direct and row_id not in context_ids,
            retrieval_min_similarity=options.min_similarity,
            index_collection=record["collection"],
            index_fingerprint=record["fingerprint"],
            retrieval_config_hash=config_hash,
            context_budget_unit="encoder_tokens",
            context_max_tokens=options.context_max_tokens,
        )
        output.append(Chunk(content=text, metadata=metadata, score=float(score)))
        seen.add(key)
        parents[parent] = parents.get(parent, 0) + 1
        if len(output) == k:
            break
    context_tokens = (
        provider.count_tokens("\n\n".join(chunk["content"] for chunk in output)) if output else 0
    )
    for chunk in output:
        chunk["metadata"]["context_tokens_total"] = context_tokens
    return output
