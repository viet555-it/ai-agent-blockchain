"""Reproducible no-network safety runs; no provider factory or signer is loaded."""

import hashlib
import json
import platform
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

from eval.safety_v2.cases import run_case
from eval.safety_v2.reports import summarize, write_reports
from eval.safety_v2.runtime import SafetyRuntime, fixture_clock
from scripts.prepare_safety_v2 import validate

ROOT = Path(__file__).resolve().parents[2]


def load_dataset():
    content = (ROOT / "eval/safety_v2/dataset.jsonl").read_text(encoding="utf-8")
    manifest = json.loads((ROOT / "eval/safety_v2/manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(content.encode()).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Safety v2 dataset does not match its manifest")
    rows = [json.loads(line) for line in content.splitlines()]
    validate(rows)
    return rows, digest


def source_manifest():
    tracked = subprocess.check_output(["git", "ls-files", "*.py"], cwd=ROOT, text=True).splitlines()
    paths = (
        set(tracked)
        | {p.relative_to(ROOT).as_posix() for p in (ROOT / "eval/safety_v2").glob("*.py")}
        | {"scripts/evaluate_safety_v2.py"}
        | {p.relative_to(ROOT).as_posix() for p in (ROOT / "scripts").glob("*safety_v2*.py")}
        | {p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").glob("test_safety_v2*.py")}
    )
    return {
        path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
        for path in sorted(paths)
        if (ROOT / path).is_file()
    }


def run_evaluation(*, mode="both", case_ids=None, output_root=None):
    rows, digest = load_dataset()
    if mode not in {"both", "policy", "fake_agent"}:
        raise ValueError("Only policy/fake_agent offline modes are supported")
    if case_ids:
        unknown = set(case_ids) - {row["id"] for row in rows}
        if unknown:
            raise ValueError(f"Unknown case IDs: {sorted(unknown)}")
        rows = [row for row in rows if row["id"] in case_ids]
    modes = ["policy", "fake_agent"] if mode == "both" else [mode]
    started = datetime.now(UTC)
    directory = Path(output_root or ROOT / "eval/safety_v2/runs") / started.strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    report = {
        "protocol": "safety-v2-offline-1",
        "dataset_status": "proposed_not_frozen",
        "started_at_utc": started.isoformat(),
        "dataset_sha256": digest,
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_status": subprocess.check_output(
            ["git", "status", "--short"], cwd=ROOT, text=True
        ).splitlines(),
        "source_sha256": source_manifest(),
        "python": platform.python_version(),
        "dependencies": {
            name: version(name) for name in ("SQLAlchemy", "web3", "pydantic", "tiktoken")
        },
        "provider": "none_or_scripted_fake",
        "live_provider_requests": 0,
        "not_measured": [
            "live_llm_injection_resistance",
            "production_rag_retrieval",
            "real_rpc_latency",
        ],
        "results": [],
    }
    temporary_root = ROOT / ".phase3/tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary_root) as temporary:
        for selected_mode in modes:
            for case in rows:
                runtime = None
                before = time.perf_counter()
                try:
                    with fixture_clock(case["fixture"]["now_utc_epoch"]):
                        runtime = SafetyRuntime(
                            Path(temporary) / f"{selected_mode}-{case['id']}.db", case
                        )
                        result = run_case(runtime, selected_mode)
                except Exception as error:
                    result = {
                        "id": case["id"],
                        "mode": selected_mode,
                        "group": case["group"],
                        "language": case["language"],
                        "label": case["label"],
                        "status": "error",
                        "passed": None,
                        "error_type": type(error).__name__,
                        "broadcast_attempts": runtime.broadcast_attempts if runtime else 0,
                    }
                finally:
                    if runtime:
                        runtime.close()
                result["total_ms"] = (time.perf_counter() - before) * 1000
                report["results"].append(result)
    report["finished_at_utc"] = datetime.now(UTC).isoformat()
    report["summaries"] = {
        selected: summarize([r for r in report["results"] if r["mode"] == selected])
        for selected in modes
    }
    write_reports(directory, report)
    return directory, report
