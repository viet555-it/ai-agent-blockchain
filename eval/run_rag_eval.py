"""Evaluate frozen gold chunks against real embeddings; never tune on holdout."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from rag.index import fingerprint
from rag.loaders import content_hash
from rag.models import DeploymentScope
from rag.retriever import RAGRetriever, RetrievalOptions, SourceScope


def percentile(values, fraction):
    if not values:
        raise ValueError("No latency samples")
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


def score_case(case, chunks, scope, options, *, error=None):
    returned = {c["metadata"]["chunk_id"] for c in chunks}
    gold = set(case["gold_chunk_ids"])
    leaks = [c["metadata"]["chunk_id"] for c in chunks
             if not scope.accepts(c["metadata"]) or (
                 c["metadata"].get("scope") == "general" and
                 c["metadata"].get("category") not in options.general_categories)]
    return dict(id=case["id"], category=case["category"], query=case["query"], mode=case["mode"],
                scope=asdict(scope), expect_empty=case["expect_empty"],
                gold_chunk_ids=case["gold_chunk_ids"],
                recall_at_5=(len(returned & gold) / len(gold) if gold else None),
                doc_hit_at_5=(bool(set(case["gold_doc_ids"]) & {c["metadata"]["doc_id"] for c in chunks}) if gold else None),
                no_match_correct=(not chunks and error is None if case["expect_empty"] else None),
                scope_leak_ids=leaks, error=error,
                returned=[dict(chunk_id=c["metadata"]["chunk_id"], doc_id=c["metadata"]["doc_id"],
                               scope=c["metadata"]["scope"], score=c["score"],
                               selection_reason=c["metadata"].get("selection_reason")) for c in chunks])


def summarize(rows):
    answerable = [r for r in rows if r["recall_at_5"] is not None]
    no_match = [r for r in rows if r["expect_empty"]]
    return dict(total=len(rows), answerable=len(answerable),
                recall_at_5=sum(r["recall_at_5"] for r in answerable) / len(answerable) if answerable else None,
                doc_hit_at_5=sum(r["doc_hit_at_5"] for r in answerable) / len(answerable) if answerable else None,
                no_match_correct=sum(r["no_match_correct"] for r in no_match), no_match_total=len(no_match),
                scope_leak_chunks=sum(len(r["scope_leak_ids"]) for r in rows),
                scope_leak_cases=sum(bool(r["scope_leak_ids"]) for r in rows), errors=sum(r["error"] is not None for r in rows))


def load_inputs(root):
    lock = json.loads((root / "eval/rag_eval_lock.json").read_text(encoding="utf-8"))
    if fingerprint({k: v for k, v in lock.items() if k != "lock_hash"}) != lock["lock_hash"]:
        raise ValueError("Evaluation lock integrity failure")
    for name, key in [("eval/rag_dataset.jsonl", "dataset_hash"),
                      ("eval/rag_gold_catalog.json", "gold_catalog_hash"), ("config/rag.json", "config_hash")]:
        if content_hash((root / name).read_text(encoding="utf-8")) != lock[key]:
            raise ValueError(f"Frozen input changed: {name}; do not tune against holdout")
    for name, expected in lock.get("runtime_hashes", {}).items():
        if content_hash((root / name).read_text(encoding="utf-8")) != expected:
            raise ValueError(f"Frozen runtime changed: {name}; create a deliberate development revision before evaluation")
    cases = [json.loads(line) for line in (root / "eval/rag_dataset.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    gold = json.loads((root / "eval/rag_gold_catalog.json").read_text(encoding="utf-8"))
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    groups = {}
    for case in cases:
        if case["split"] not in {"dev", "holdout"} or case["mode"] not in {"deployment", "source"}:
            raise ValueError("Invalid split or mode")
        if groups.setdefault(case["group_id"], case["split"]) != case["split"]:
            raise ValueError("Intent group leaks between dev and holdout")
        if case["expect_empty"] != (not case["gold_chunk_ids"]):
            raise ValueError("Expected-empty/gold labels contradict")
        if len(case["gold_chunk_ids"]) != len(set(case["gold_chunk_ids"])):
            raise ValueError("Duplicate gold chunk")
        if any(i not in gold for i in case["gold_chunk_ids"]):
            raise ValueError("Unknown gold chunk")
        if set(case["gold_doc_ids"]) != {gold[i]["metadata"]["doc_id"] for i in case["gold_chunk_ids"]}:
            raise ValueError("Gold document/chunk mismatch")
    expected = Counter(abi=6, web3=4, source=4, scope=3, outside=3)
    for split in ("dev", "holdout"):
        if Counter(c["category"] for c in cases if c["split"] == split) != expected:
            raise ValueError("Expected 20 cases in each balanced split")
    return lock, cases, gold


def make_scope(case, manifest):
    if case["mode"] == "deployment":
        values = dict(manifest["deployment_scope"])
        values.update(case["scope_overrides"])
        return DeploymentScope(**values)
    versions = {s["doc_version"] for s in manifest["sources"] if s["scope"] == "source_only" and s["usage"] == "ingest"}
    if len(versions) != 1:
        raise ValueError("Benchmark requires explicit unique source base version")
    return SourceScope(**dict(dict(doc_version=next(iter(versions))), **case["scope_overrides"]))


async def run(root, split):
    started = time.perf_counter()
    lock, all_cases, gold = load_inputs(root)
    if split == "holdout":
        dev = json.loads((root / "eval/rag_results_dev.json").read_text(encoding="utf-8"))
        if dev["lock_hash"] != lock["lock_hash"]:
            raise ValueError("Run dev with the same frozen inputs before holdout")
    from rag.embeddings import SentenceEmbeddingProvider
    from rag.index import IndexStore
    from rag.settings import RAGSettings
    settings = RAGSettings.load("config/rag.json", root=root)
    config = json.loads((root / "config/rag.json").read_text(encoding="utf-8"))
    manifest_text = (root / "knowledge/manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    provider = await asyncio.to_thread(SentenceEmbeddingProvider, model_id=settings.model_id,
                                      revision=settings.revision, cache_dir=settings.cache_dir,
                                      batch_size=settings.batch_size, threads=settings.threads, offline=True)
    store = IndexStore(settings.index_dir)
    active = store.active(expected_embedding=provider.identity)
    if active is None or active["fingerprint"] != lock["index_fingerprint"] or active["source_manifest_hash"] != lock["source_manifest_hash"] or content_hash(manifest_text) != lock["source_manifest_hash"]:
        raise ValueError("Index/corpus changed after benchmark freeze")
    stored = store.collection().get(ids=list(gold), include=["documents", "metadatas"])
    if len(stored["ids"]) != len(gold):
        raise ValueError("Missing gold chunks in index")
    for i, text, flat in zip(stored["ids"], stored["documents"], stored["metadatas"]):
        if text != gold[i]["content"] or json.loads(flat["record_json"]) != gold[i]["metadata"]:
            raise ValueError("Gold evidence differs from stored index")
    options = RetrievalOptions.from_dict(config["retrieval"])
    retrievers = {}
    cases = [c for c in all_cases if c["split"] == split]
    for case in cases:
        scope = make_scope(case, manifest)
        key = fingerprint(asdict(scope))
        if key not in retrievers:
            retrievers[key] = RAGRetriever(provider, store, scope, options=options, expected_manifest_hash=lock["source_manifest_hash"])
        case["scope_key"] = key
        for i in case["gold_chunk_ids"]:
            if not scope.accepts(gold[i]["metadata"]):
                raise ValueError("Gold chunk is outside labeled scope")
    startup_ms = (time.perf_counter() - started) * 1000
    rows, samples = [], []
    try:
        for case in cases:
            retriever = retrievers[case["scope_key"]]
            query_started = time.perf_counter()
            error = None
            try:
                chunks = await retriever.retrieve(case["query"], k=5)
            except Exception as exc:
                chunks, error = [], f"{type(exc).__name__}: {exc}"
            row = score_case(case, chunks, retriever.scope, options, error=error)
            row["latency_ms"] = (time.perf_counter() - query_started) * 1000
            rows.append(row)
        # All scopes have now received their first query; measure repeated calls,
        # not new model loads, and include empty-scope/no-match paths in the mix.
        for n in range(lock["benchmark_queries"]):
            case = cases[n % len(cases)]
            query_started = time.perf_counter()
            await retrievers[case["scope_key"]].retrieve(case["query"], k=5)
            samples.append(dict(case_id=case["id"], category=case["category"],
                                latency_ms=(time.perf_counter() - query_started) * 1000))
    finally:
        for retriever in retrievers.values():
            await retriever.aclose()
    summary = summarize(rows)
    warm = dict(count=len(samples), p50_ms=percentile([s["latency_ms"] for s in samples], .50),
                p95_ms=percentile([s["latency_ms"] for s in samples], .95))
    gates = dict(recall_at_5=summary["recall_at_5"] >= .90,
                 no_scope_leaks=summary["scope_leak_chunks"] == 0,
                 no_errors=summary["errors"] == 0,
                 no_match=summary["no_match_correct"] == summary["no_match_total"], warm_p95=warm["p95_ms"] <= 500)
    report = dict(schema_version=1, split=split, lock_hash=lock["lock_hash"], dataset_hash=lock["dataset_hash"],
                  config_hash=lock["config_hash"], index_fingerprint=active["fingerprint"],
                  model=provider.identity, options=asdict(options), summary=summary,
                  categories={category: summarize([r for r in rows if r["category"] == category]) for category in sorted({r["category"] for r in rows})},
                  startup_ms=startup_ms, first_query_ms=rows[0]["latency_ms"], warm=warm, warm_samples=samples,
                  machine=dict(platform=platform.platform(), processor=platform.processor(), logical_cpus=os.cpu_count(),
                               python=platform.python_version(), threads=settings.threads),
                  gates=gates, passed=all(gates.values()), rows=rows,
                  limitations="Curated small local split; intent isolation from prior P5/P6, same corpus/topics. Gold is curated evidence, not exhaustive relevance. Cold means process/model initialization with OS/model cache available, not first download. Sequential warm samples after accuracy pass; no concurrency/load or LLM-quality claim.")
    path = root / f"eval/rag_results_{split}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(split=split, summary=summary, warm=warm, gates=gates, passed=report["passed"])), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["dev", "holdout"], required=True)
    args = parser.parse_args()
    report = asyncio.run(run(Path(__file__).resolve().parents[1], args.split))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
