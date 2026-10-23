"""Build or roll back a local RAG index; offline by default after model setup."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from rag.chunking import chunk_documents
from rag.embeddings import SentenceEmbeddingProvider
from rag.index import IndexStore, fingerprint
from rag.loaders import content_hash, load_corpus
from rag.settings import RAGSettings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path("config/rag.json"))
    parser.add_argument("--manifest", type=Path, default=Path("knowledge/manifest.json"))
    parser.add_argument("--verify-git", action="store_true")
    parser.add_argument("--allow-download", action="store_true", help="Allow downloading the pinned model on initial setup")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate and chunk with real tokenizer, no embedding/DB writes")
    mode.add_argument("--rebuild", action="store_true", help="Force a new generation, including when model identity changes")
    mode.add_argument("--rollback", metavar="GENERATION", help="Activate a retained validated generation without loading the model")
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        root = args.root.resolve()
        settings = RAGSettings.load(args.config, root=root)
        if args.rollback:
            result = IndexStore(settings.index_dir).rollback(args.rollback)
        else:
            # Invalid corpus fails before any database mutation or model download.
            docs = load_corpus(args.manifest, root=root, verify_git=args.verify_git)
            model_started = time.perf_counter()
            provider = SentenceEmbeddingProvider(
                model_id=settings.model_id, revision=settings.revision, cache_dir=settings.cache_dir,
                batch_size=settings.batch_size, threads=settings.threads, offline=not args.allow_download,
            )
            model_seconds = time.perf_counter() - model_started
            chunks = chunk_documents(docs, budget=provider.budget, prefix_style=settings.prefix_style)
            manifest_path = args.manifest if args.manifest.is_absolute() else root / args.manifest
            manifest_hash = content_hash(manifest_path.read_text(encoding="utf-8"))
            corpus_hash = fingerprint(sorted(
                [(doc.metadata["doc_id"], doc.metadata["content_hash"], doc.metadata["scope"], doc.metadata["doc_version"])
                 for doc in docs]
            ))
            if args.dry_run:
                result = dict(status="dry_run", doc_count=len(docs), chunk_count=len(chunks),
                              embedding=provider.identity, corpus_hash=corpus_hash)
            else:
                result = IndexStore(settings.index_dir).build(
                    chunks, provider, corpus_hash=corpus_hash, source_manifest_hash=manifest_hash,
                    batch_size=settings.batch_size, rebuild=args.rebuild,
                )
            result["max_chunk_tokens"] = max(chunk.metadata["token_count"] for chunk in chunks)
            result["model_load_seconds"] = round(model_seconds, 3)
        result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    except Exception as exc:
        parser.exit(1, f"RAG ingestion failed ({type(exc).__name__}): {exc}\n")


if __name__ == "__main__":
    main()
