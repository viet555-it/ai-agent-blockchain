"""Immutable Chroma generations with an atomic active pointer and explicit rollback."""

from __future__ import annotations

import copy
import json
import math
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from rag.chunking import PreparedChunk, SPLITTER_VERSION
from rag.loaders import content_hash, parse_json


class IndexError(ValueError):
    pass


class Embedder(Protocol):
    @property
    def identity(self) -> dict[str, Any]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def fingerprint(value: Any) -> str:
    return content_hash(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))


def _generation(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"rag_[0-9a-f]{32}", name):
        raise IndexError("Invalid generation name")
    return name


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def _write_lock(root: Path):
    path = root / "build.lock"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise IndexError("Another writer or a stale build.lock exists; inspect it before retrying") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_at": datetime.now(timezone.utc).isoformat()}))
        yield
    finally:
        path.unlink(missing_ok=True)


def _flat_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    flat = {key: value for key, value in metadata.items() if type(value) in (str, int, float, bool)}
    if "record_json" in metadata:
        raise IndexError("record_json is a reserved storage metadata key")
    # Preserve null source_commit and nested evidence without passing unsupported
    # null/dict values to Chroma's scalar filter metadata.
    flat["record_json"] = json.dumps(metadata, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return flat


class IndexStore:
    def __init__(self, path: str | Path) -> None:
        self.root = Path(path).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "generations").mkdir(exist_ok=True)
        import chromadb
        from chromadb.config import Settings

        self.client = chromadb.PersistentClient(
            path=str(self.root / "chroma"), settings=Settings(anonymized_telemetry=False),
        )

    def _record(self, name: str) -> dict[str, Any]:
        name = _generation(name)
        path = self.root / "generations" / f"{name}.json"
        if not path.is_file():
            raise IndexError(f"Missing generation manifest: {name}")
        record = parse_json(path.read_text(encoding="utf-8"), str(path))
        if not isinstance(record, dict) or record.get("collection") != name or record.get("schema_version") != 1:
            raise IndexError("Invalid generation manifest")
        expected = record.get("record_hash")
        if fingerprint({key: value for key, value in record.items() if key != "record_hash"}) != expected:
            raise IndexError("Generation manifest integrity check failed")
        collection = self.client.get_collection(name, embedding_function=None)
        if collection.metadata.get("fingerprint") != record["fingerprint"] or collection.count() != record["chunk_count"]:
            raise IndexError("Collection metadata/count does not match generation manifest")
        return record

    def active(self, *, expected_embedding: dict[str, Any] | None = None) -> dict[str, Any] | None:
        path = self.root / "active.json"
        if not path.is_file():
            return None
        pointer = parse_json(path.read_text(encoding="utf-8"), str(path))
        if not isinstance(pointer, dict) or pointer.get("schema_version") != 1:
            raise IndexError("Invalid active pointer")
        record = self._record(pointer.get("collection"))
        if pointer.get("record_hash") != record["record_hash"]:
            raise IndexError("Active pointer does not match generation manifest")
        if expected_embedding is not None and record["embedding"] != expected_embedding:
            raise IndexError("Embedding identity mismatch; explicitly rebuild rather than mix vectors")
        return record

    def _activate(self, record: dict[str, Any]) -> None:
        _atomic_json(self.root / "active.json", dict(
            schema_version=1, collection=record["collection"], record_hash=record["record_hash"],
        ))

    def build(
        self, chunks: list[PreparedChunk], embedder: Embedder, *, corpus_hash: str,
        source_manifest_hash: str, batch_size: int = 32, rebuild: bool = False,
    ) -> dict[str, Any]:
        if not chunks:
            raise IndexError("Refusing to replace active index with an empty corpus")
        if type(batch_size) is not int or batch_size < 1:
            raise IndexError("batch_size must be a positive integer")
        identity = copy.deepcopy(embedder.identity)
        dimension = identity.get("dimension")
        if type(dimension) is not int or dimension <= 0:
            raise IndexError("Embedding dimension must be a positive integer")
        ids = [chunk.metadata["chunk_id"] for chunk in chunks]
        if len(set(ids)) != len(ids):
            raise IndexError("Duplicate input chunk IDs")
        for chunk in chunks:
            if chunk.metadata.get("budget_unit") != "tokens":
                raise IndexError("Byte-preview chunks cannot be embedded as a production index")
            if chunk.metadata.get("tokenizer_id") != f"{identity['model_id']}@{identity['revision']}":
                raise IndexError("Chunk tokenizer does not match embedding model/revision")
            if chunk.metadata.get("measured_length", identity["max_tokens"] + 1) > identity["max_tokens"]:
                raise IndexError("Chunk exceeds encoder token limit")
        config = dict(
            corpus_hash=corpus_hash, source_manifest_hash=source_manifest_hash, embedding=identity,
            splitter_version=SPLITTER_VERSION, distance_metric="cosine",
            chunk_ids_hash=fingerprint(sorted(ids)),
            records_hash=fingerprint([chunk.to_dict() for chunk in chunks]),
        )
        build_hash = fingerprint(config)
        with _write_lock(self.root):
            previous = self.active()
            if previous and previous["embedding"] != identity and not rebuild:
                raise IndexError("Embedding identity changed; use rebuild to create an isolated generation")
            if previous and previous["fingerprint"] == build_hash and not rebuild:
                return {**previous, "status": "unchanged"}
            name = "rag_" + uuid.uuid4().hex
            collection = self.client.create_collection(
                name=name, embedding_function=None,
                metadata={"fingerprint": build_hash, "dimension": dimension},
                configuration={"hnsw": {"space": "cosine"}},
            )
            activated = False
            try:
                for start in range(0, len(chunks), batch_size):
                    batch = chunks[start:start + batch_size]
                    vectors = embedder.embed([chunk.content for chunk in batch])
                    if len(vectors) != len(batch) or any(
                        len(vector) != dimension or not all(math.isfinite(value) for value in vector)
                        for vector in vectors
                    ):
                        raise IndexError("Embedding batch shape or values are invalid")
                    collection.upsert(
                        ids=[chunk.metadata["chunk_id"] for chunk in batch],
                        documents=[chunk.content for chunk in batch],
                        metadatas=[_flat_metadata(chunk.metadata) for chunk in batch], embeddings=vectors,
                    )
                if collection.count() != len(chunks):
                    raise IndexError("Staging collection count mismatch")
                stored_ids = collection.get(include=[])["ids"]
                if set(stored_ids) != set(ids):
                    raise IndexError("Staging collection IDs mismatch")
                record = dict(
                    schema_version=1, collection=name, fingerprint=build_hash, **config,
                    chunk_count=len(chunks), doc_count=len({c.metadata["doc_id"] for c in chunks}),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    previous_collection=previous["collection"] if previous else None,
                )
                record["record_hash"] = fingerprint(record)
                _atomic_json(self.root / "generations" / f"{name}.json", record)
                self._record(name)
                self._activate(record)
                activated = True
                return {**record, "status": "built"}
            finally:
                if not activated:
                    # Never delete or mutate the old active generation on failure.
                    self.client.delete_collection(name)
                    (self.root / "generations" / f"{name}.json").unlink(missing_ok=True)

    def rollback(self, name: str) -> dict[str, Any]:
        with _write_lock(self.root):
            record = self._record(name)
            self._activate(record)
            return {**record, "status": "rolled_back"}

    def collection(self, *, expected_embedding: dict[str, Any] | None = None):
        record = self.active(expected_embedding=expected_embedding)
        if record is None:
            raise IndexError("No active index; run ingestion first")
        return self.client.get_collection(record["collection"], embedding_function=None)
