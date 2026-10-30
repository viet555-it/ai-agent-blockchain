"""Atomic JSON checkpoints and final JSON/CSV evaluation reporting."""

from __future__ import annotations

import csv
import json
import time
from datetime import UTC, datetime

from eval.e2e_metrics import percentile, summarize


def write_report(directory, report):
    temporary = directory / "results.tmp"
    for attempt in range(6):
        try:
            temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(directory / "results.json")
            return
        except PermissionError:
            if attempt == 5:
                raise
            time.sleep(0.1 * (attempt + 1))


def finalize_report(directory, report, *, safety, inner, provider):
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report["summary"] = summarize(report["results"])
    report["not_run_cases"] = sum(row.get("not_run", False) for row in report["results"])
    report["safety_summary"] = {
        "n": len(report["safety_results"]),
        "planned": 20 if safety else 0,
        "not_run": 20 - len(report["safety_results"]) if safety else 0,
        "passed": sum(row["score"]["success"] for row in report["safety_results"]),
    }
    samples = [row["latency_ms"] for row in report["latency_samples"]]
    report["infrastructure_latency"] = {
        "n": len(samples),
        "p50_ms": percentile(samples, 50),
        "p95_ms": percentile(samples, 95),
        "failures": sum(
            bool(row["error"]) or row["status_code"] != 200 for row in report["latency_samples"]
        ),
    }
    if inner:
        report.update(
            generation_requests=inner.call_count,
            token_usage=inner.total_usage,
            last_provider_error=inner.last_error,
        )
        report["approved_request_budget"] = provider.live_budget.snapshot()
    write_report(directory, report)
    with (directory / "samples.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "id",
                "phase",
                "latency_ms",
                "rag_ms",
                "llm_ms",
                "rpc_ms",
                "policy_ms",
                "prepare_ms",
                "success",
            ]
        )
        for row in report["results"] + report["safety_results"]:
            writer.writerow(
                [
                    row["id"],
                    row["phase"],
                    row["latency_ms"],
                    *[row["stage_ms"][name] for name in ["rag", "llm", "rpc", "policy", "prepare"]],
                    row["score"]["success"],
                ]
            )
    print(
        json.dumps(
            {
                "status": report["status"],
                "summary": report["summary"],
                "safety": report["safety_summary"],
                "infrastructure_latency": report["infrastructure_latency"],
                "evidence": str(directory / "results.json"),
            }
        ),
        flush=True,
    )
