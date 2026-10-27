"""Run G3.0 suites with fake LLM, blank credentials and loopback-only EVM."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from backend.runtime_profiles import isolated_test_environment

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", choices=["unit", "rag", "contracts", "local_evm", "all"], default="unit"
    )
    args = parser.parse_args()
    env = isolated_test_environment()
    evidence = ROOT / ".phase3"
    evidence.mkdir(exist_ok=True)
    env["TIKTOKEN_CACHE_DIR"] = str(evidence / "tiktoken")
    env["TEMP"] = env["TMP"] = str(evidence / "tmp")
    (evidence / "tmp").mkdir(exist_ok=True)
    agent_tests = [str(p.relative_to(ROOT)) for p in sorted((ROOT / "tests").glob("test_*.py"))]
    node = shutil.which("node")
    hardhat = ROOT / "contracts/node_modules/hardhat/internal/cli/cli.js"
    suites = {
        "unit": (
            [
                sys.executable,
                "-m",
                "pytest",
                *agent_tests,
                "backend/tests",
                "-q",
                "--ignore=backend/tests/test_integration_blockchain.py",
                "--ignore=backend/tests/test_api_local_evm.py",
                "--ignore=backend/tests/test_transactions_local_evm.py",
                "-k",
                "not LocalIntegrationTests",
            ],
            ROOT,
        ),
        "rag": ([sys.executable, "-m", "unittest", "discover", "-s", "tests/rag", "-v"], ROOT),
        "contracts": ([node or "node", str(hardhat), "test"], ROOT / "contracts"),
        "local_evm": ([sys.executable, "backend/run_integration_tests.py"], ROOT),
    }
    selected = list(suites) if args.suite == "all" else [args.suite]
    results = []
    for name in selected:
        command, cwd = suites[name]
        child_env = dict(env)
        if name == "unit":
            child_env["PHASE3_PROFILE"] = "unit"
            child_env.pop("LOCAL_TEST_RPC", None)
            child_env.pop("RUN_INTEGRATION_TESTS", None)
        log = evidence / f"{name}.log"
        print(f"Running {name}; log: {log}", flush=True)
        with log.open("w", encoding="utf-8") as output:
            process = subprocess.run(
                command,
                cwd=cwd,
                env=child_env,
                stdout=output,
                stderr=subprocess.STDOUT,
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
        results.append({"suite": name, "exit_code": process.returncode, "log": log.name})
        print(
            "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]),
            flush=True,
        )
        if process.returncode:
            break
    (evidence / f"{args.suite}-summary.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    return 0 if all(r["exit_code"] == 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
