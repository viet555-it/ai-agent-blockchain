"""Run an evaluation with owned infrastructure and explicit options."""

from __future__ import annotations

import importlib.metadata
import json
import logging
import subprocess
import traceback
from datetime import UTC, datetime
from pathlib import Path

from dotenv import dotenv_values

from agent.llm.gemini import GeminiProvider
from config.environment import PROJECT_ROOT
from eval.e2e_budget import RequestBudget
from eval.e2e_metrics import validate_dataset
from eval.e2e_runtime import EvaluationRuntime

from .cases import not_run, run_case
from .options import EvaluationOptions, EvaluationUsageError, validate_options
from .protocol import freeze_protocol, protocol, require_frozen_protocol
from .provider import MeasuredProvider
from .reports import finalize_report, write_report


def run_evaluation(
    options: EvaluationOptions, *, root: Path = PROJECT_ROOT, evidence_dir: Path | None = None
) -> int:
    options = validate_options(options)
    values = dotenv_values(root / ".env")
    model = values.get("LLM_MODEL", "")
    key = values.get("GEMINI_API_KEY", "")
    configured_provider = values.get("LLM_PROVIDER", "")
    del values
    rows = [
        json.loads(line)
        for line in (root / "eval/e2e_dataset.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    safety = [
        json.loads(line)
        for line in (root / "eval/e2e_safety.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    validate_dataset(rows, safety)
    pinned = protocol(model, root=root)
    if options.freeze:
        freeze_protocol(options.dev_report, pinned, root=root)
        return 0
    if options.split == "holdout":
        require_frozen_protocol(pinned, root=root)
    if options.mode == "gemini" and (
        not options.allow_live_llm or not key or not model or configured_provider != "gemini"
    ):
        raise EvaluationUsageError(
            "Real mode requires --allow-live-llm and the configured root Gemini key/model"
        )
    return evaluate_session(
        options, rows, safety, pinned, model, key, root=root, evidence_dir=evidence_dir
    )


def evaluate_session(
    args: EvaluationOptions,
    rows,
    safety,
    pinned,
    model,
    key,
    *,
    root: Path = PROJECT_ROOT,
    evidence_dir: Path | None = None,
) -> int:
    logging.disable(logging.CRITICAL)
    started = datetime.now(UTC)
    directory = evidence_dir or (
        root
        / "eval/phase3"
        / (started.strftime("%Y%m%dT%H%M%SZ") + "-" + args.mode + "-" + args.split)
    )
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        "mode": args.mode,
        "split": args.split,
        "protocol": pinned,
        "started_at_utc": started.isoformat(),
        "fake_is_not_model_accuracy": args.mode == "fake",
        "results": [],
        "safety_results": [],
        "latency_samples": [],
        "timing_note": "RPC overlaps prepare; stage times must not be added. Broadcast/receipt are not measured in this no-send benchmark.",
        "generation_request_cap": args.request_cap,
        "status": "RUNNING",
        "git_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ["web3", "google-genai", "fastapi", "chromadb"]
        },
    }
    inner = (
        GeminiProvider(key, model, max_calls=args.request_cap, max_output_tokens=512)
        if args.mode == "gemini"
        else None
    )
    provider = MeasuredProvider(inner)
    if args.mode == "gemini":
        provider.live_budget = RequestBudget(root / ".phase3/g35-gemini-budget.json")
        provider.budget_phase = "safety" if args.safety_only else args.split
    if args.preview_payload:
        provider.preview_path = directory / "payload-preview.jsonl"
        provider.model = model
    selected = [] if args.safety_only else [row for row in rows if row["split"] == args.split]
    try:
        with EvaluationRuntime(
            provider, llm_mode="gemini" if args.preview_payload else args.mode, model=model
        ) as runtime:
            report.update(
                bindings=runtime.bindings,
                fixture_deployments_before_benchmark=1,
                startup_ms=runtime.startup_ms,
                app_cold_start_ms=runtime.app_cold_start_ms,
            )
            halted = False
            for index, case in enumerate(selected):
                result = run_case(
                    runtime, provider, case, mode=args.mode, session="eval-" + case["id"]
                )
                report["results"].append(result)
                write_report(directory, report)
                print(
                    json.dumps(
                        {
                            "id": case["id"],
                            "success": result["score"]["success"],
                            "latency_ms": round(result["latency_ms"], 1),
                        }
                    ),
                    flush=True,
                )
                if result["attempted_writes"]:
                    raise RuntimeError("System attempted a forbidden broadcast; stopped by guard")
                if (
                    args.mode == "gemini"
                    and result["error"]
                    and (
                        (inner.last_error or {}).get("http_status") == 429
                        or result["generation_requests"] == 0
                    )
                ):
                    report["halt_reason"] = "quota_or_generation_budget"
                    report["results"].extend(
                        not_run(pending, report["halt_reason"], runtime.bindings)
                        for pending in selected[index + 1 :]
                    )
                    halted = True
                    break
            if args.safety and not halted:
                for case in safety:
                    result = run_case(
                        runtime,
                        provider,
                        case,
                        mode=args.mode,
                        safety=True,
                        session="safety-" + case["id"],
                    )
                    report["safety_results"].append(result)
                    write_report(directory, report)
                    if (
                        args.mode == "gemini"
                        and result["error"]
                        and (
                            (inner.last_error or {}).get("http_status") == 429
                            or result["generation_requests"] == 0
                        )
                    ):
                        report["halt_reason"] = "quota_or_generation_budget"
                        halted = True
                        break
            latency_cases = [
                row
                for row in rows
                if row["split"] == "dev" and row["category"] in {"read", "write"}
            ]
            for i in range(args.latency_samples):
                case = latency_cases[i % len(latency_cases)]
                result = run_case(runtime, provider, case, mode="fake", session="latency")
                report["latency_samples"].append(
                    {
                        "id": case["id"],
                        "latency_ms": result["latency_ms"],
                        "stage_ms": result["stage_ms"],
                        "error": result["error"],
                        "status_code": result["status_code"],
                    }
                )
            report.update(
                nonce_before=runtime.nonce,
                nonce_after=runtime.w3.eth.get_transaction_count(
                    runtime.bindings["wallet"], "pending"
                ),
                broadcast_count=0,
                attempted_writes=runtime.rpc.attempted_writes,
                rpc_methods=dict(runtime.rpc.methods),
            )
        report["status"] = "LIMIT_REACHED" if halted else "COMPLETED"
    except Exception as error:
        report["status"] = "INFRASTRUCTURE_FAILURE"
        report["failure_type"] = type(error).__name__
        report["failure_location"] = traceback.extract_tb(error.__traceback__)[-1].name
        completed = {row["id"] for row in report["results"]}
        report["results"].extend(
            not_run(case, "infrastructure_not_run", report.get("bindings"))
            for case in selected
            if case["id"] not in completed
        )
    finally:
        finalize_report(directory, report, safety=args.safety, inner=inner, provider=provider)
    return 0 if report["status"] == "COMPLETED" and report.get("attempted_writes") == 0 else 1
