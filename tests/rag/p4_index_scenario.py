"""Run real Chroma lifecycle checks in a child process so Windows releases DB files."""

import json
import sys
from pathlib import Path

from rag.chunking import PreparedChunk
from rag.index import IndexError, IndexStore, fingerprint


class TestEmbedder:
    def __init__(self, revision="a" * 40, fail=False):
        self.revision = revision
        self.fail = fail
        self.calls = 0

    @property
    def identity(self):
        return dict(model_id="test/fake", revision=self.revision, dimension=3,
                    max_tokens=64, normalize_embeddings=True)

    def embed(self, texts):
        self.calls += 1
        if self.fail and self.calls > 1:
            raise RuntimeError("Injected encoder failure")
        return [[1.0, 0.0, 0.0] for _ in texts]


def chunks(entries, embedder):
    return [PreparedChunk(text, dict(
        chunk_id=doc_id + ":" + fingerprint(text), doc_id=doc_id,
        source_commit=None, source_origin="workspace", scope="general",
        budget_unit="tokens", measured_length=len(text),
        tokenizer_id=f"test/fake@{embedder.revision}",
        derived_from=[{"source_path": "test.md", "source_commit": None}],
    )) for doc_id, text in entries]


def build(store, entries, embedder, **kwargs):
    return store.build(chunks(entries, embedder), embedder, corpus_hash=fingerprint(entries),
                       source_manifest_hash=fingerprint(entries), batch_size=1, **kwargs)


def lifecycle(path):
    store = IndexStore(path)
    embedder = TestEmbedder()
    initial = [("a", "first document"), ("b", "second document")]
    first = build(store, initial, embedder)
    assert first["chunk_count"] == 2
    same = build(store, initial, embedder)
    assert same["status"] == "unchanged" and same["collection"] == first["collection"]
    assert len(store.client.list_collections()) == 1
    updated = [("a", "changed document")]
    second = build(store, updated, embedder)
    assert second["collection"] != first["collection"]
    got = store.collection().get(include=["documents", "metadatas"])
    assert got["documents"] == ["changed document"]
    assert json.loads(got["metadatas"][0]["record_json"])["source_commit"] is None
    # Force a distinct generation even for identical content, preserving rollback.
    rebuilt = build(store, updated, embedder, rebuild=True)
    assert rebuilt["collection"] != second["collection"]
    store.rollback(first["collection"])
    assert store.collection().count() == 2
    return dict(initial_collection=first["collection"], final_count=2, unchanged=True,
                update_delete=True, rebuild=True, rollback=True)


def failures(path):
    store = IndexStore(path)
    embedder = TestEmbedder()
    first = build(store, [("a", "original")], embedder)
    before = (Path(path) / "active.json").read_bytes()
    try:
        build(store, [("a", "changed"), ("b", "fail after first batch")], TestEmbedder(fail=True))
        raise AssertionError("Expected encoder failure")
    except RuntimeError:
        pass
    assert (Path(path) / "active.json").read_bytes() == before
    assert len(store.client.list_collections()) == 1
    incompatible = TestEmbedder(revision="b" * 40)
    try:
        build(store, [("a", "new model")], incompatible)
        raise AssertionError("Expected model mismatch")
    except IndexError:
        pass
    isolated = build(store, [("a", "new model")], incompatible, rebuild=True)
    assert isolated["embedding"]["revision"] == "b" * 40
    try:
        store.active(expected_embedding=embedder.identity)
        raise AssertionError("Expected read-time model mismatch")
    except IndexError:
        pass
    store.rollback(first["collection"])
    (Path(path) / "build.lock").write_text("test concurrent writer", encoding="utf-8")
    try:
        try:
            build(store, [("a", "busy")], embedder)
            raise AssertionError("Expected lock error")
        except IndexError:
            pass
    finally:
        (Path(path) / "build.lock").unlink()
    for name in ("../outside", "missing", "rag_" + "0" * 32):
        try:
            store.rollback(name)
            raise AssertionError("Expected invalid/missing rollback")
        except IndexError:
            pass
    assert store.active()["collection"] == first["collection"]
    bad_chunk = chunks([("a", "bytes")], embedder)
    bad_chunk[0].metadata["budget_unit"] = "utf8_bytes"
    try:
        store.build(bad_chunk, embedder, corpus_hash="x", source_manifest_hash="x")
        raise AssertionError("Expected preview chunk rejection")
    except IndexError:
        pass
    return dict(failure_keeps_active=True, model_isolation=True, lock=True, preview_rejected=True)


def reopen(path):
    store = IndexStore(path)
    record = store.active(expected_embedding=TestEmbedder().identity)
    assert record and record["chunk_count"] == 2
    assert store.collection().count() == 2
    return dict(reopened=True, count=2)


if __name__ == "__main__":
    command, path = sys.argv[1:]
    result = {"lifecycle": lifecycle, "failures": failures, "reopen": reopen}[command](path)
    print(json.dumps(result))
