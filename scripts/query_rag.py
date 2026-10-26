"""Query the standalone local RAG module; no LLM, HTTP server or RPC required."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from rag.loaders import parse_json
from rag.models import DeploymentScope
from rag.retriever import (
    InvalidQuery, RAGRetriever, RetrievalOptions, RetrievalTimeout,
    RetrievalUnavailable, SourceScope,
)


class UsageError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise UsageError(message)


@dataclass(frozen=True)
class QueryRequest:
    root: Path
    config: Path
    scope_mode: str
    scope: DeploymentScope | SourceScope
    options: RetrievalOptions
    query: str
    k: int


def parser() -> Parser:
    command = Parser(description=__doc__)
    command.add_argument("--query", required=True, help="Question or ABI signature")
    command.add_argument("--k", type=int, default=5, help="Maximum chunks, 1..10")
    command.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    command.add_argument("--config", type=Path, default=Path("config/rag.json"))
    command.add_argument("--scope", choices=("deployment", "source"), default="deployment")
    command.add_argument("--source-version", help="Source review version; auto-selected only if unique in manifest")
    command.add_argument("--chain-id", type=int, help="Override deployment chain for an explicit scope lookup")
    command.add_argument("--contract-address", help="Override deployment address; does not change index data")
    command.add_argument("--abi-hash", help="Override deployment ABI hash")
    command.add_argument("--doc-version", help="Override deployment document version")
    command.add_argument("--no-general", action="store_true", help="Exclude general Web3 documents")
    command.add_argument("--timeout-seconds", type=float, help="Query deadline, excluding model initialization")
    command.add_argument("--json", action="store_true", help="Write one machine-readable JSON object to stdout")
    return command


def prepare(args: argparse.Namespace) -> QueryRequest:
    if not args.query.strip():
        raise InvalidQuery("query must be non-empty text")
    if not 1 <= args.k <= 10:
        raise InvalidQuery("k must be an integer in 1..10")
    if args.timeout_seconds is not None and (not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0):
        raise InvalidQuery("timeout-seconds must be positive and finite")
    overrides = dict(chain_id=args.chain_id, contract_address=args.contract_address,
                     abi_hash=args.abi_hash, doc_version=args.doc_version)
    if args.scope == "source" and any(value is not None for value in overrides.values()):
        raise InvalidQuery("Deployment overrides cannot be used with --scope source")
    if args.scope == "deployment" and args.source_version is not None:
        raise InvalidQuery("source-version requires --scope source")
    root = args.root.resolve()
    config = args.config if args.config.is_absolute() else root / args.config
    try:
        raw = parse_json(config.read_text(encoding="utf-8"), str(config))
        if not isinstance(raw, dict):
            raise ValueError("RAG config must be an object")
        options = RetrievalOptions.from_dict(raw.get("retrieval", {}))
        path = root / "knowledge/manifest.json"
        manifest = parse_json(path.read_text(encoding="utf-8"), str(path))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != 2:
            raise ValueError("Expected knowledge manifest schema 2")
        base_scope = DeploymentScope(**manifest["deployment_scope"])
    except (OSError, UnicodeError, ValueError, TypeError, KeyError) as exc:
        raise RetrievalUnavailable(f"Cannot read local RAG configuration: {exc}") from exc
    if len(args.query) > options.max_query_chars:
        raise InvalidQuery(f"query exceeds {options.max_query_chars} characters")
    if args.timeout_seconds is not None:
        options = replace(options, timeout_seconds=args.timeout_seconds)
    if args.scope == "deployment":
        values = asdict(base_scope)
        values.update({key: value for key, value in overrides.items() if value is not None})
        if args.no_general:
            values["include_general"] = False
        try:
            scope = DeploymentScope(**values)
        except (TypeError, ValueError) as exc:
            raise InvalidQuery(f"Invalid deployment scope: {exc}") from exc
    else:
        sources = manifest.get("sources")
        if not isinstance(sources, list) or not all(isinstance(source, dict) for source in sources):
            raise RetrievalUnavailable("Manifest sources must be an array of objects")
        source_versions = [source.get("doc_version") for source in sources
                           if source.get("scope") == "source_only" and source.get("usage") == "ingest"]
        if any(not isinstance(version, str) or not version.strip() for version in source_versions):
            raise RetrievalUnavailable("Manifest contains an invalid source version")
        versions = set(source_versions)
        if args.source_version is not None:
            if args.source_version not in versions:
                raise InvalidQuery("source-version is not an approved ingest source version")
            version = args.source_version
        elif len(versions) == 1:
            version = next(iter(versions))
        else:
            raise InvalidQuery("Choose --source-version explicitly; the manifest has zero or multiple source versions")
        scope = SourceScope(version, include_general=not args.no_general)
    return QueryRequest(root, args.config, args.scope, scope, options, args.query.strip(), args.k)


async def execute(request: QueryRequest, *, factory=None) -> dict[str, Any]:
    started = time.perf_counter()
    create = factory or RAGRetriever.create
    retriever = await create(root=request.root, config=request.config, scope=request.scope, options=request.options)
    startup_ms = (time.perf_counter() - started) * 1000
    try:
        query_started = time.perf_counter()
        results = await retriever.retrieve(request.query, k=request.k)
        retrieval_ms = (time.perf_counter() - query_started) * 1000
    finally:
        await retriever.aclose()
    return dict(
        status="ok" if results else "no_match", query=request.query, k=request.k,
        scope_mode=request.scope_mode, scope=asdict(request.scope),
        count=len(results), score_metric="cosine_similarity",
        retrieval_min_similarity=request.options.min_similarity,
        timing=dict(startup_ms=round(startup_ms, 2), retrieval_ms=round(retrieval_ms, 2),
                    total_ms=round((time.perf_counter() - started) * 1000, 2)),
        results=results, error=None,
    )


def emit(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        return
    print(f"Trạng thái: {payload['status']}")
    if payload.get("error"):
        print(f"Lỗi: {payload['error']['message']}")
        return
    scope = payload["scope"]
    if payload["scope_mode"] == "deployment":
        print(f"Deployment: chain {scope['chain_id']} | {scope['contract_address']} | {scope['doc_version']}")
    else:
        print(f"Source review: {scope['doc_version']} (hành vi source, chưa xác minh deployment)")
    print(f"Kết quả: {payload['count']}/{payload['k']} | cosine similarity, không phải xác suất đúng")
    timing = payload["timing"]
    print(f"Khởi tạo: {timing['startup_ms']:.2f} ms | Truy xuất: {timing['retrieval_ms']:.2f} ms")
    if not payload["results"]:
        print("Không có đoạn nào đủ liên quan trong scope và context budget đã chọn.")
    for index, chunk in enumerate(payload["results"], 1):
        meta = chunk["metadata"]
        revision = (meta.get("source_commit") or "workspace chưa commit")
        print(f"\n[{index}] {meta['title']} | cosine={chunk['score']:.4f}")
        print(f"Nguồn: {meta['source_path']} @ {revision}")
        print(f"Scope: {meta['scope']} | version: {meta['doc_version']} | {meta['verification_status']}")
        print(f"Chunk: {meta['chunk_id']} | chọn bởi: {meta.get('selection_reason', 'semantic')}")
        print(chunk["content"])


def main(argv=None, *, factory=None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in arguments
    try:
        args = parser().parse_args(arguments)
        request = prepare(args)
        payload = asyncio.run(execute(request, factory=factory))
        code = 0 if payload["status"] == "ok" else 3
    except (UsageError, InvalidQuery) as exc:
        code, status, error = 2, "invalid_query", exc
    except RetrievalTimeout as exc:
        code, status, error = 5, "timeout", exc
    except (RetrievalUnavailable, ImportError) as exc:
        code, status, error = 4, "unavailable", exc
    except KeyboardInterrupt:
        code, status, error = 130, "cancelled", KeyboardInterrupt("Đã hủy truy vấn.")
    except Exception as exc:
        code, status, error = 1, "internal_error", exc
    if code not in (0, 3):
        payload = dict(status=status, count=0, results=[], error=dict(type=type(error).__name__, message=str(error)))
    emit(payload, as_json=as_json)
    return code


def utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    utf8_console()
    raise SystemExit(main())
