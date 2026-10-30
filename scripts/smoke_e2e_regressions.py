"""Observed-case regression smoke; never presented as a fresh holdout run."""

import argparse
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from agent.llm.gemini import GeminiProvider
from config.environment import PROJECT_ROOT
from eval.e2e.cases import run_case
from eval.e2e.protocol import protocol, sha
from eval.e2e.provider import MeasuredProvider
from eval.e2e.reports import write_report
from eval.e2e_budget import RequestBudget
from eval.e2e_runtime import EvaluationRuntime

CASES = ("E13", "E31", "E59", "E15", "E21", "E25", "E37", "E01")
SAFETY = ("S19", "S20")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fake", "gemini"], default="fake")
    parser.add_argument("--allow-live-llm", action="store_true")
    parser.add_argument("--request-cap", type=int, choices=range(1, 21), default=20)
    parser.add_argument("--case", action="append", choices=(*CASES, "E14"), dest="case_ids")
    parser.add_argument("--skip-safety", action="store_true")
    args = parser.parse_args()
    selected_cases = tuple(dict.fromkeys(args.case_ids or CASES))
    selected_safety = () if args.skip_safety else SAFETY
    if args.mode == "gemini" and not args.allow_live_llm:
        parser.error("Gemini requires --allow-live-llm and an approved payload scope")
    values = dotenv_values(PROJECT_ROOT / ".env")
    model = values.get("LLM_MODEL") or "gemini-3.5-flash-lite"
    key = values.get("GEMINI_API_KEY") or ""
    del values
    if args.mode == "gemini" and not key:
        parser.error("Missing GEMINI_API_KEY in root .env")
    inner = (
        GeminiProvider(key, model, max_calls=args.request_cap, max_output_tokens=512)
        if args.mode == "gemini"
        else None
    )
    del key
    provider = MeasuredProvider(inner)
    if inner:
        provider.live_budget = RequestBudget(PROJECT_ROOT / ".phase3/g35-gemini-budget.json")
    directory = (
        PROJECT_ROOT
        / "eval/phase3"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + args.mode + "-postfix-regression")
    )
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        "purpose": "observed_case_regression_not_holdout",
        "mode": args.mode,
        "fake_is_not_model_accuracy": args.mode == "fake",
        "status": "RUNNING",
        "protocol": protocol(model),
        "runner_sha256": sha(Path(__file__)),
        "results": [],
        "safety_results": [],
        "planned_cases": list(selected_cases),
        "planned_safety": list(selected_safety),
        "per_run_request_cap": args.request_cap,
    }
    logging.disable(logging.CRITICAL)
    write_report(directory, report)
    try:
        with EvaluationRuntime(provider, llm_mode=args.mode, model=model) as runtime:
            report.update(startup_ms=runtime.startup_ms, nonce_before=runtime.nonce)
            for filename, ids, safety in [
                ("e2e_dataset.jsonl", selected_cases, False),
                ("e2e_safety.jsonl", selected_safety, True),
            ]:
                cases = {
                    row["id"]: row
                    for row in map(
                        json.loads,
                        (PROJECT_ROOT / "eval" / filename).read_text(encoding="utf-8").splitlines(),
                    )
                }
                provider.budget_phase = "safety" if safety else "dev"
                for case_id in ids:
                    if inner and inner.call_count >= args.request_cap:
                        raise RuntimeError("Smoke request cap exhausted; remaining cases not run")
                    row = run_case(
                        runtime,
                        provider,
                        cases[case_id],
                        mode=args.mode,
                        safety=safety,
                        session="regression-" + case_id,
                    )
                    row["provider_diagnostic"] = (
                        dict(inner.last_error) if inner and inner.last_error else None
                    )
                    report["safety_results" if safety else "results"].append(row)
                    write_report(directory, report)
                    print(
                        json.dumps(
                            {
                                "id": case_id,
                                "success": row["score"]["success"],
                                "generation_requests": row["generation_requests"],
                                "latency_ms": round(row["latency_ms"], 1),
                                "diagnostic": row["provider_diagnostic"],
                            }
                        ),
                        flush=True,
                    )
                    if row["attempted_writes"] or (
                        inner and (inner.last_error or {}).get("http_status") == 429
                    ):
                        raise RuntimeError("Unsafe attempt or provider quota; stopping smoke")
            report.update(
                nonce_after=runtime.w3.eth.get_transaction_count(
                    runtime.bindings["wallet"], "pending"
                ),
                attempted_writes=runtime.rpc.attempted_writes,
                status="COMPLETED",
            )
    except Exception as error:
        report.update(status="INCOMPLETE", failure_type=type(error).__name__)
    finally:
        report["generation_requests"] = inner.call_count if inner else 0
        report["token_usage"] = inner.total_usage if inner else {}
        report["approved_request_budget"] = (
            provider.live_budget.snapshot() if provider.live_budget else None
        )
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        write_report(directory, report)
    rows = report["results"] + report["safety_results"]
    passed = sum(row["score"]["success"] for row in rows)
    planned = len(selected_cases) + len(selected_safety)
    print(
        json.dumps(
            {
                "status": report["status"],
                "passed": passed,
                "planned": planned,
                "evidence": str(directory / "results.json"),
            }
        ),
        flush=True,
    )
    return 0 if report["status"] == "COMPLETED" and passed == planned else 1


if __name__ == "__main__":
    raise SystemExit(main())
