"""Run browser E2E with isolated DB/deployment, FakeLLM, and owned local processes."""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from backend.runtime_profiles import isolated_test_environment

ROOT = Path(__file__).resolve().parents[1]


def port():
    with socket.socket() as handle:
        handle.bind(("127.0.0.1", 0))
        return handle.getsockname()[1]


def wait_for(url, process, rpc=False):
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError("Owned test process exited; inspect .phase3/wallet-e2e logs")
        try:
            response = (
                httpx.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []},
                    timeout=1,
                )
                if rpc
                else httpx.get(url + "/api/health", timeout=1)
            )
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError("Owned test process startup timed out")


def main():
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required")
    evidence = ROOT / ".phase3/wallet-e2e"
    evidence.mkdir(parents=True, exist_ok=True)
    rpc_port, app_port = port(), port()
    env = isolated_test_environment()
    env.update(
        WALLET_E2E_TEST="1",
        WALLET_E2E_RPC=f"http://127.0.0.1:{rpc_port}",
        LOCAL_RPC_URL=f"http://127.0.0.1:{rpc_port}",
        APP_ORIGIN=f"http://127.0.0.1:{app_port}",
        TIKTOKEN_CACHE_DIR=str(ROOT / ".phase3/tiktoken"),
    )
    owned = []
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="run-", dir=evidence) as temporary:
        env["WALLET_E2E_DIRECTORY"] = temporary
        with (
            (evidence / "hardhat.log").open("w") as hardhat_log,
            (evidence / "api.log").open("w") as api_log,
        ):
            try:
                hardhat = subprocess.Popen(
                    [
                        node,
                        str(ROOT / "contracts/node_modules/hardhat/internal/cli/cli.js"),
                        "node",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        str(rpc_port),
                    ],
                    cwd=ROOT / "contracts",
                    env=env,
                    stdout=hardhat_log,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
                owned.append(hardhat)
                wait_for(env["WALLET_E2E_RPC"], hardhat, rpc=True)
                api = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        "scripts.wallet_e2e_app:create",
                        "--factory",
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(app_port),
                    ],
                    cwd=ROOT,
                    env=env,
                    stdout=api_log,
                    stderr=subprocess.STDOUT,
                    creationflags=flags,
                )
                owned.append(api)
                wait_for(env["APP_ORIGIN"], api)
                result = subprocess.run(
                    [
                        node,
                        str(ROOT / "frontend/node_modules/@playwright/test/cli.js"),
                        "test",
                        "--config",
                        "playwright.config.cjs",
                    ],
                    cwd=ROOT / "frontend",
                    env=env,
                    creationflags=flags,
                )
                (evidence / "summary.json").write_text(json.dumps({"exit_code": result.returncode}))
                return result.returncode
            finally:
                for process in reversed(owned):
                    if process.poll() is None:
                        process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
