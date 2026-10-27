"""Async, scope-bound retrieval over a pinned local model and active Chroma generation."""

from __future__ import annotations

import asyncio
import copy
import json
import math
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from rag.index import IndexStore, fingerprint
from rag.loaders import abi_type, content_hash, parse_json
from rag.models import Chunk, DeploymentScope


class InvalidQuery(ValueError):
    pass


class RetrievalUnavailable(RuntimeError):
    """Index, encoder or stored data is unavailable; this is not a no-match."""


class RetrievalTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class SourceScope:
    """Explicit review of source documentation; never a deployment capability claim."""

    doc_version: str
    include_general: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.doc_version, str) or not self.doc_version.strip():
            raise ValueError("Source doc_version is required")
        if type(self.include_general) is not bool:
            raise ValueError("include_general must be boolean")

    def accepts(self, metadata: dict[str, Any]) -> bool:
        if metadata.get("scope") == "general":
            return self.include_general
        return metadata.get("scope") == "source_only" and metadata.get("doc_version") == self.doc_version


@dataclass(frozen=True)
class RetrievalOptions:
    min_similarity: float = 0.45
    candidate_pool: int = 32
    context_max_tokens: int = 1024
    max_query_chars: int = 2000
    timeout_seconds: float = 15.0
    max_concurrency: int = 1
    max_per_parent: int = 2
    parent_context: bool = False
    general_categories: tuple[str, ...] = ("web3",)

    def __post_init__(self) -> None:
        if type(self.parent_context) is not bool:
            raise ValueError("parent_context must be boolean")
        if type(self.min_similarity) not in (int, float) or not math.isfinite(self.min_similarity) or not -1 <= self.min_similarity <= 1:
            raise ValueError("min_similarity must be finite and between -1 and 1")
        for name, lower, upper in (
            ("candidate_pool", 10, 100), ("context_max_tokens", 1, 16384),
            ("max_query_chars", 1, 10000), ("max_concurrency", 1, 8), ("max_per_parent", 1, 10),
        ):
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer in {lower}..{upper}")
        if type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive and finite")
        if not isinstance(self.general_categories, tuple) or any(not isinstance(c, str) or not c for c in self.general_categories):
            raise ValueError("general_categories must be a tuple of category names")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RetrievalOptions":
        if not isinstance(value, dict):
            raise ValueError("retrieval config must be an object")
        value = dict(value)
        if "general_categories" in value:
            if not isinstance(value["general_categories"], (list, tuple)):
                raise ValueError("general_categories must be an array")
            value["general_categories"] = tuple(value["general_categories"])
        return cls(**value)


def _type_signature(text: str) -> str:
    text = text.strip()
    if text.startswith("("):
        depth, close = 0, None
        for index, character in enumerate(text):
            depth += character == "("
            depth -= character == ")"
            if depth == 0:
                close = index
                break
        if close is None or not re.fullmatch(r"(?:\[(?:[1-9][0-9]*)?\])*", text[close + 1:]):
            raise ValueError("Invalid tuple signature")
        return "(" + ",".join(_type_signature(p) for p in _parameters(text[1:close])) + ")" + text[close + 1:]
    return abi_type({"type": text})


def _parameters(text: str) -> list[str]:
    if not text.strip():
        return []
    depth, start, result = 0, 0, []
    for index, character in enumerate(text):
        depth += character == "("
        depth -= character == ")"
        if character == "," and depth == 0:
            result.append(text[start:index])
            start = index + 1
    result.append(text[start:])
    return result


def explicit_signatures(query: str) -> set[str]:
    """Extract ABI type signatures, not calls containing addresses/amount values."""
    found: set[str] = set()
    for match in re.finditer(r"\b([A-Za-z_$][\w$]*)\s*\(", query):
        start, depth, end = match.end(), 1, None
        for index in range(start, len(query)):
            depth += query[index] == "("
            depth -= query[index] == ")"
            if depth == 0:
                end = index
                break
        if end is None:
            continue
        try:
            params = ",".join(_type_signature(p) for p in _parameters(query[start:end]))
        except ValueError:
            continue
        found.add(match[1] + "(" + params + ")")
    return found


def _signatures(metadata: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    if metadata.get("function_signature"):
        result.add(metadata["function_signature"])
    if metadata.get("function_signatures_json"):
        items = parse_json(metadata["function_signatures_json"], "stored function signatures")
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise RetrievalUnavailable("Invalid stored signature list")
        result.update(items)
    return result


def _restore(row_id: str, flat: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(flat, dict) or not isinstance(flat.get("record_json"), str):
        raise RetrievalUnavailable("Stored chunk has no provenance record")
    metadata = parse_json(flat["record_json"], "record_json")
    required = ("chunk_id", "doc_id", "title", "category", "source_path", "content_hash",
                "scope", "doc_version", "verification_status", "chunk_hash", "parent_id")
    if not isinstance(metadata, dict) or any(not isinstance(metadata.get(key), str) or not metadata[key] for key in required):
        raise RetrievalUnavailable("Stored chunk has incomplete metadata")
    if metadata["chunk_id"] != row_id or metadata.get("usage") != "ingest":
        raise RetrievalUnavailable("Stored chunk identity/usage is invalid")
    origin, commit = metadata.get("source_origin"), metadata.get("source_commit")
    if "source_commit" not in metadata or origin not in {"git", "workspace"}:
        raise RetrievalUnavailable("Stored chunk is missing source provenance")
    if origin == "git" and (not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise RetrievalUnavailable("Stored Git source_commit is invalid")
    if origin == "workspace" and commit is not None:
        raise RetrievalUnavailable("Stored workspace source_commit must be null")
    for key, value in metadata.items():
        if type(value) in (str, int, float, bool) and (key not in flat or type(flat[key]) is not type(value) or flat[key] != value):
            raise RetrievalUnavailable("Stored filter metadata differs from provenance record")
    return metadata


def _similarity(distance: float) -> float:
    if not math.isfinite(distance) or not -0.0001 <= distance <= 2.0001:
        raise RetrievalUnavailable("Invalid cosine distance from index")
    return max(-1.0, min(1.0, 1.0 - distance))


class RAGRetriever:
    def __init__(
        self, provider: Any, store: IndexStore, scope: DeploymentScope | SourceScope, *,
        options: RetrievalOptions | None = None, expected_manifest_hash: str | None = None,
    ) -> None:
        if not isinstance(scope, (DeploymentScope, SourceScope)):
            raise ValueError("An explicit immutable deployment/source scope is required")
        self._provider, self._store, self._scope = provider, store, scope
        self.options = options or RetrievalOptions()
        self._manifest_hash = expected_manifest_hash
        self._slots = asyncio.BoundedSemaphore(self.options.max_concurrency)
        self._executor = ThreadPoolExecutor(max_workers=self.options.max_concurrency, thread_name_prefix="rag-query")
        self._catalog: tuple[str, dict[str, dict[str, Any]]] | None = None
        self._closed = False
        self._config_hash = fingerprint(asdict(self.options))

    @property
    def scope(self) -> DeploymentScope | SourceScope:
        return self._scope

    @classmethod
    async def create(
        cls, *, root: str | Path, config: str | Path = "config/rag.json",
        scope: DeploymentScope | SourceScope | None = None, options: RetrievalOptions | None = None,
    ) -> "RAGRetriever":
        def initialize():
            from rag.embeddings import SentenceEmbeddingProvider
            from rag.settings import RAGSettings

            directory = Path(root).resolve()
            settings = RAGSettings.load(config, root=directory)
            config_path = Path(config) if Path(config).is_absolute() else directory / config
            raw_config = parse_json(config_path.read_text(encoding="utf-8"), str(config_path))
            configured_options = options or RetrievalOptions.from_dict(raw_config.get("retrieval", {}))
            manifest_text = (directory / "knowledge/manifest.json").read_text(encoding="utf-8")
            manifest = parse_json(manifest_text, "knowledge manifest")
            bound_scope = scope or DeploymentScope(**manifest["deployment_scope"])
            provider = SentenceEmbeddingProvider(
                model_id=settings.model_id, revision=settings.revision, cache_dir=settings.cache_dir,
                batch_size=settings.batch_size, threads=settings.threads, offline=True,
            )
            store = IndexStore(settings.index_dir)
            active = store.active(expected_embedding=provider.identity)
            if active is None or active["source_manifest_hash"] != content_hash(manifest_text):
                raise RetrievalUnavailable("Index is missing or stale; ingest the approved manifest first")
            return cls(provider, store, bound_scope, options=configured_options,
                       expected_manifest_hash=content_hash(manifest_text))

        try:
            return await asyncio.to_thread(initialize)
        except RetrievalUnavailable:
            raise
        except Exception as exc:
            raise RetrievalUnavailable(f"Cannot initialize local RAG: {type(exc).__name__}: {exc}") from exc

    async def retrieve(self, query: str, k: int = 5) -> list[Chunk]:
        if not isinstance(query, str) or not query.strip():
            raise InvalidQuery("query must be non-empty text")
        if len(query) > self.options.max_query_chars:
            raise InvalidQuery(f"query exceeds {self.options.max_query_chars} characters")
        if type(k) is not int or not 1 <= k <= 10:
            raise InvalidQuery("k must be an integer in 1..10")
        if self._closed:
            raise RetrievalUnavailable("Retriever is closed")
        started = time.monotonic()
        try:
            await asyncio.wait_for(self._slots.acquire(), self.options.timeout_seconds)
        except TimeoutError as exc:
            raise RetrievalTimeout("Timed out waiting for a retrieval worker") from exc
        try:
            if self._closed:
                raise RetrievalUnavailable("Retriever is closed")
            future = asyncio.get_running_loop().run_in_executor(self._executor, self._search, query.strip(), k)
        except BaseException:
            self._slots.release()
            raise

        def completed(done):
            self._slots.release()
            if not done.cancelled():
                done.exception()  # Consume an eventual error after the caller timed out/cancelled.

        future.add_done_callback(completed)
        remaining = max(0, self.options.timeout_seconds - (time.monotonic() - started))
        try:
            # A timeout cannot kill native inference. Keep its slot until the real
            # worker completes; don't create an unbounded queue of abandoned work.
            return await asyncio.wait_for(asyncio.shield(future), remaining)
        except TimeoutError as exc:
            raise RetrievalTimeout("Retrieval exceeded its deadline") from exc

    async def aclose(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def __aenter__(self) -> "RAGRetriever":
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()

    def _get_catalog(self, collection, record) -> dict[str, dict[str, Any]]:
        if self._catalog and self._catalog[0] == record["fingerprint"]:
            return self._catalog[1]
        stored = collection.get(include=["metadatas"])
        catalog = {row_id: _restore(row_id, metadata) for row_id, metadata in zip(stored["ids"], stored["metadatas"], strict=True)}
        self._catalog = (record["fingerprint"], catalog)
        return catalog

    def _search(self, query: str, k: int) -> list[Chunk]:
        try:
            return self._search_checked(query, k)
        except (InvalidQuery, RetrievalUnavailable):
            raise
        except Exception as exc:
            raise RetrievalUnavailable(f"Retrieval failed: {type(exc).__name__}: {exc}") from exc

    def _search_checked(self, query: str, k: int) -> list[Chunk]:
        if self._provider.count_tokens(query) > self._provider.identity["max_tokens"]:
            raise InvalidQuery("query exceeds the encoder token limit; shorten it instead of truncating")
        record = self._store.active(expected_embedding=self._provider.identity)
        if record is None:
            raise RetrievalUnavailable("No active index")
        if record.get("distance_metric") != "cosine":
            raise RetrievalUnavailable("Retriever requires a cosine index")
        if self._manifest_hash and record["source_manifest_hash"] != self._manifest_hash:
            raise RetrievalUnavailable("Index manifest changed; recreate the retriever for the new corpus")
        # Capture one generation for the whole request, even if a writer switches active.json.
        collection = self._store.client.get_collection(record["collection"], embedding_function=None)
        configuration = collection.configuration
        if not isinstance(configuration, dict) or (configuration.get("hnsw") or {}).get("space") != "cosine":
            raise RetrievalUnavailable("Collection configuration is not cosine HNSW")
        catalog = self._get_catalog(collection, record)
        allowed = {
            key: meta for key, meta in catalog.items() if self.scope.accepts(meta)
            and (meta["scope"] != "general" or meta["category"] in self.options.general_categories)
        }
        if not allowed:
            return []
        requested = explicit_signatures(query)
        signatures = {key: _signatures(meta) for key, meta in catalog.items()}
        global_names = {sig.split("(", 1)[0] for items in signatures.values() for sig in items}
        named = {name for name in global_names if re.search(r"(?<![\w$])" + re.escape(name) + r"(?![\w$])", query)}
        allowed_signatures = set().union(*(signatures[key] for key in allowed))
        if requested and not requested.issubset(allowed_signatures):
            return []  # An unsupported overload/deployment must not fall back to unrelated general docs.
        exact_ids = {key for key in allowed if signatures[key] & requested} if requested else {
            key for key in allowed if any(sig.split("(", 1)[0] in named for sig in signatures[key])
        }
        # Source prose can explain a getter (e.g. supply cap) without having a
        # section named cap(). Deployment queries must not borrow another scope's
        # interface merely because the identifier exists elsewhere in the index.
        if named and not exact_ids and (
            isinstance(self.scope, DeploymentScope)
            or not any(meta["scope"] == "source_only" for meta in allowed.values())
        ):
            return []
        direct_symbol = bool(named and re.fullmatch(r"`?[A-Za-z_$][\w$]*`?", query))
        if direct_symbol and not exact_ids:
            return []
        vector = self._provider.embed([query])[0]
        candidates: dict[str, tuple[str, dict[str, Any], float, bool]] = {}
        if requested or direct_symbol:
            # A syntactically exact interface lookup can succeed even when prose
            # similarity is low; the returned score remains the true cosine value.
            lookup = collection.get(ids=sorted(exact_ids), include=["documents", "metadatas", "embeddings"])
            for row_id, text, flat, embedding in zip(lookup["ids"], lookup["documents"], lookup["metadatas"], lookup["embeddings"], strict=True):
                denominator = math.sqrt(sum(x*x for x in vector) * sum(float(x)*float(x) for x in embedding))
                if denominator <= 0:
                    raise RetrievalUnavailable("Zero vector in cosine index")
                similarity = sum(x * float(y) for x, y in zip(vector, embedding, strict=True)) / denominator
                candidates[row_id] = (text, _restore(row_id, flat), _similarity(1.0 - similarity), True)
        else:
            result = collection.query(
                query_embeddings=[vector], ids=sorted(allowed),
                n_results=min(len(allowed), max(self.options.candidate_pool, k * 4)),
                include=["documents", "metadatas", "distances"],
            )
            for row_id, text, flat, distance in zip(result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0], strict=True):
                candidates[row_id] = (text, _restore(row_id, flat), _similarity(float(distance)), False)
            # Include named candidates outside ANN top-N, still subject to the prose threshold.
            missing = exact_ids - candidates.keys()
            if missing:
                lookup = collection.get(ids=sorted(missing), include=["documents", "metadatas", "embeddings"])
                for row_id, text, flat, embedding in zip(lookup["ids"], lookup["documents"], lookup["metadatas"], lookup["embeddings"], strict=True):
                    denominator = math.sqrt(sum(x*x for x in vector) * sum(float(x)*float(x) for x in embedding))
                    if denominator <= 0:
                        raise RetrievalUnavailable("Zero vector in cosine index")
                    similarity = sum(x * float(y) for x, y in zip(vector, embedding, strict=True)) / denominator
                    candidates[row_id] = (text, _restore(row_id, flat), _similarity(1.0 - similarity), False)
        ranked = sorted(candidates.items(), key=lambda item: (item[0] not in exact_ids, -item[1][2], item[0]))
        # A relevant fragment may refer to another fragment of the same section.
        # Keep the actual cosine score; eligibility comes from an accepted seed,
        # not from pretending that a low-similarity continuation met the cutoff.
        context_ids: set[str] = set()
        if self.options.parent_context:
            seed_parents = []
            for row_id, (_, meta, score, direct) in ranked:
                if (direct or score >= self.options.min_similarity) and meta["parent_id"] not in seed_parents:
                    seed_parents.append(meta["parent_id"])
            siblings = {i for i, meta in allowed.items() if meta["parent_id"] in seed_parents} - candidates.keys()
            if siblings:
                lookup = collection.get(ids=sorted(siblings), include=["documents", "metadatas", "embeddings"])
                for row_id, text, flat, embedding in zip(lookup["ids"], lookup["documents"], lookup["metadatas"], lookup["embeddings"], strict=True):
                    denominator = math.sqrt(sum(x*x for x in vector) * sum(float(x)*float(x) for x in embedding))
                    if denominator <= 0:
                        raise RetrievalUnavailable("Zero vector in cosine index")
                    similarity = sum(x * float(y) for x, y in zip(vector, embedding, strict=True)) / denominator
                    candidates[row_id] = (text, _restore(row_id, flat), _similarity(1.0 - similarity), False)
            ranked = []
            for parent in seed_parents:
                items = [(i, value) for i, value in candidates.items() if value[1]["parent_id"] == parent]
                items.sort(key=lambda item: (-item[1][2], item[0]))
                ranked.extend(items)
                context_ids.update(i for i, (_, _, score, direct) in items if not direct and score < self.options.min_similarity)
        output: list[Chunk] = []
        seen: set[str] = set()
        parents: dict[str, int] = {}
        for row_id, (text, meta, score, direct) in ranked:
            if row_id not in allowed or not self.scope.accepts(meta):
                raise RetrievalUnavailable("Candidate escaped the bound scope")
            if not isinstance(text, str) or content_hash(text) != meta["chunk_hash"]:
                raise RetrievalUnavailable("Candidate content hash mismatch")
            if not direct and row_id not in context_ids and score < self.options.min_similarity:
                continue
            key = meta["chunk_hash"]
            parent = meta["parent_id"]
            if key in seen or parents.get(parent, 0) >= self.options.max_per_parent:
                continue
            joined = "\n\n".join([chunk["content"] for chunk in output] + [text])
            if self._provider.count_tokens(joined) > self.options.context_max_tokens:
                continue
            metadata = copy.deepcopy(meta)
            metadata.update(
                score_metric="cosine_similarity", cosine_distance=1.0 - score,
                selection_reason="parent_context" if row_id in context_ids else ("exact_signature" if requested else ("symbol_name" if row_id in exact_ids else "semantic")),
                threshold_applied=not direct and row_id not in context_ids, retrieval_min_similarity=self.options.min_similarity,
                index_collection=record["collection"], index_fingerprint=record["fingerprint"],
                retrieval_config_hash=self._config_hash,
                context_budget_unit="encoder_tokens", context_max_tokens=self.options.context_max_tokens,
            )
            output.append(Chunk(content=text, metadata=metadata, score=float(score)))
            seen.add(key)
            parents[parent] = parents.get(parent, 0) + 1
            if len(output) == k:
                break
        context_tokens = self._provider.count_tokens("\n\n".join(chunk["content"] for chunk in output)) if output else 0
        for chunk in output:
            chunk["metadata"]["context_tokens_total"] = context_tokens
        return output
