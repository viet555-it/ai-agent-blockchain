"""Run the offline pre-change safety baseline with the project's isolated environment."""

from __future__ import annotations

import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from backend.runtime_profiles import isolated_test_environment

ROOT = Path(__file__).resolve().parents[1]
SUITES = [
    "backend/tests/test_guardrail_policy.py",
    "backend/tests/test_wallet_history.py",
    "tests/test_policy.py",
    "tests/test_e2e_protocol.py",
    "tests/test_e2e_metrics.py",
    "tests/test_eval_and_coverage.py",
]


def main():
    started = datetime.now(UTC).isoformat()
    directory = ROOT / "eval/safety_v2/baseline" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True)
    temporary = ROOT / ".phase3/tmp"
    temporary.mkdir(parents=True, exist_ok=True)
    env = isolated_test_environment()
    env["TEMP"] = env["TMP"] = str(temporary)
    env["TIKTOKEN_CACHE_DIR"] = str(ROOT / ".phase3/tiktoken")
    command = [
        sys.executable,
        "-m",
        "pytest",
        *SUITES,
        "-q",
        "--tb=short",
        f"--junitxml={directory / 'junit.xml'}",
    ]
    before = time.perf_counter()
    with (directory / "pytest.log").open("w", encoding="utf-8") as output:
        result = subprocess.run(
            command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT, check=False
        )
    suites = ET.parse(directory / "junit.xml").getroot().findall("testsuite")
    totals = {
        key: sum(int(s.get(key, 0)) for s in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    totals["passed"] = totals["tests"] - sum(totals[k] for k in ("failures", "errors", "skipped"))
    report = {
        "kind": "existing_tests_pre_guardrail_implementation",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.perf_counter() - before, 3),
        "git_revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "git_status": subprocess.check_output(
            ["git", "status", "--short"], cwd=ROOT, text=True
        ).splitlines(),
        "python": sys.version,
        "suites": SUITES,
        "exit_code": result.returncode,
        "counts": totals,
        "count_semantics": "JUnit records include subtests; consult pytest.log for parent test counts",
        "environment": "isolated_test_environment; workspace temp; cached tokenizer",
        "not_measured": ["safety_v2_40_cases", "live_llm", "daily_limit_ledger_not_implemented"],
        "evidence_directory": directory.relative_to(ROOT).as_posix(),
    }
    (directory / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print((directory / "pytest.log").read_text(encoding="utf-8"))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
