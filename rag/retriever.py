"""Async, scope-bound retrieval over a pinned local model and active Chroma generation."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from rag.index import IndexStore, fingerprint
from rag.loaders import content_hash, parse_json
from rag.models import Chunk, DeploymentScope
from rag.retrieval import contracts
from rag.retrieval.candidates import cosine_similarity as _similarity  # noqa: F401
from rag.retrieval.metadata import restore_metadata as _restore
from rag.retrieval.metadata import stored_signatures as _signatures  # noqa: F401
from rag.retrieval.search import search
from rag.retrieval.signatures import (
    _parameters as _parameters,
)
from rag.retrieval.signatures import (
    _type_signature as _type_signature,
)
from rag.retrieval.signatures import (
    explicit_signatures as explicit_signatures,
)

InvalidQuery = contracts.InvalidQuery
RetrievalOptions = contracts.RetrievalOptions
RetrievalTimeout = contracts.RetrievalTimeout
RetrievalUnavailable = contracts.RetrievalUnavailable
SourceScope = contracts.SourceScope


class RAGRetriever:
    def __init__(
        self,
        provider: Any,
        store: IndexStore,
        scope: DeploymentScope | SourceScope,
        *,
        options: RetrievalOptions | None = None,
        expected_manifest_hash: str | None = None,
    ) -> None:
        if not isinstance(scope, (DeploymentScope, SourceScope)):
            raise ValueError("An explicit immutable deployment/source scope is required")
        self._provider, self._store, self._scope = provider, store, scope
        self.options = options or RetrievalOptions()
        self._manifest_hash = expected_manifest_hash
        self._slots = asyncio.BoundedSemaphore(self.options.max_concurrency)
        self._executor = ThreadPoolExecutor(
            max_workers=self.options.max_concurrency, thread_name_prefix="rag-query"
        )
        self._catalog: tuple[str, dict[str, dict[str, Any]]] | None = None
        self._closed = False
        self._config_hash = fingerprint(asdict(self.options))

    @property
    def scope(self) -> DeploymentScope | SourceScope:
        return self._scope

    @classmethod
    async def create(
        cls,
        *,
        root: str | Path,
        config: str | Path = "config/rag.json",
        scope: DeploymentScope | SourceScope | None = None,
        options: RetrievalOptions | None = None,
    ) -> RAGRetriever:
        def initialize():
            from rag.embeddings import SentenceEmbeddingProvider
            from rag.settings import RAGSettings

            directory = Path(root).resolve()
            settings = RAGSettings.load(config, root=directory)
            config_path = Path(config) if Path(config).is_absolute() else directory / config
            raw_config = parse_json(config_path.read_text(encoding="utf-8"), str(config_path))
            configured_options = options or RetrievalOptions.from_dict(
                raw_config.get("retrieval", {})
            )
            manifest_text = (directory / "knowledge/manifest.json").read_text(encoding="utf-8")
            manifest = parse_json(manifest_text, "knowledge manifest")
            bound_scope = scope or DeploymentScope(**manifest["deployment_scope"])
            provider = SentenceEmbeddingProvider(
                model_id=settings.model_id,
                revision=settings.revision,
                cache_dir=settings.cache_dir,
                batch_size=settings.batch_size,
                threads=settings.threads,
                offline=True,
            )
            store = IndexStore(settings.index_dir)
            active = store.active(expected_embedding=provider.identity)
            if active is None or active["source_manifest_hash"] != content_hash(manifest_text):
                raise RetrievalUnavailable(
                    "Index is missing or stale; ingest the approved manifest first"
                )
            return cls(
                provider,
                store,
                bound_scope,
                options=configured_options,
                expected_manifest_hash=content_hash(manifest_text),
            )

        try:
            return await asyncio.to_thread(initialize)
        except RetrievalUnavailable:
            raise
        except Exception as exc:
            raise RetrievalUnavailable(
                f"Cannot initialize local RAG: {type(exc).__name__}: {exc}"
            ) from exc

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
            future = asyncio.get_running_loop().run_in_executor(
                self._executor, self._search, query.strip(), k
            )
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

    async def __aenter__(self) -> RAGRetriever:
        return self

    async def __aexit__(self, *args) -> None:
        await self.aclose()

    def _get_catalog(self, collection, record) -> dict[str, dict[str, Any]]:
        if self._catalog and self._catalog[0] == record["fingerprint"]:
            return self._catalog[1]
        stored = collection.get(include=["metadatas"])
        catalog = {
            row_id: _restore(row_id, metadata)
            for row_id, metadata in zip(stored["ids"], stored["metadatas"], strict=True)
        }
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
        return search(
            query,
            k,
            provider=self._provider,
            store=self._store,
            scope=self.scope,
            options=self.options,
            expected_manifest_hash=self._manifest_hash,
            config_hash=self._config_hash,
            get_catalog=self._get_catalog,
        )
