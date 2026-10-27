"""One-command automated test runner for unit and live EVM integration tests.

Starts a local Hardhat node (if not already running), executes all tests,
and cleans up processes automatically.
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from web3 import Web3

ROOT_DIR = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT_DIR / "contracts"
RPC_URL = "http://127.0.0.1:8545"
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
from backend.runtime_profiles import isolated_test_environment


def is_node_ready(url: str) -> bool:
    try:
        w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 1.0}))
        return w3.is_connected() and w3.eth.chain_id == 31337
    except Exception:
        return False


def main():
    print("=" * 70)
    print(" BLOCKCHAIN SERVICE & NETWORK INTEGRATION TEST RUNNER ")
    print("=" * 70)

    node_process = None
    node_log = None
    started_node = False
    env = isolated_test_environment()

    if is_node_ready(RPC_URL):
        print(f"[+] Detected already running Hardhat node on {RPC_URL}")
    else:
        print(f"[*] Spawning local Hardhat node in {CONTRACTS_DIR}...")
        # Run Node directly so the owned process is the node, not an npm shell.
        node_cmd = shutil.which("node")
        if node_cmd is None:
            raise RuntimeError("Node.js is required for local EVM integration")
        log_dir = ROOT_DIR / ".phase3"
        log_dir.mkdir(exist_ok=True)
        node_log = (log_dir / "hardhat-node.log").open("w", encoding="utf-8")
        node_process = subprocess.Popen(
            [node_cmd, str(CONTRACTS_DIR / "node_modules/hardhat/internal/cli/cli.js"),
             "node", "--hostname", "127.0.0.1"],
            cwd=str(CONTRACTS_DIR),
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            stdout=node_log,
            stderr=subprocess.STDOUT,
        )

        started_node = True

        # Wait for node to initialize
        ready = False
        for _ in range(100):
            if node_process.poll() is not None:
                break
            time.sleep(0.5)
            if is_node_ready(RPC_URL):
                ready = True
                break

        if not ready:
            print("[-] Error: Failed to start Hardhat local node within timeout.")
            if node_process:
                if node_process.poll() is None:
                    node_process.terminate()
                node_process.wait(timeout=5)
            node_log.close()
            print("See .phase3/hardhat-node.log for startup diagnostics.")
            sys.exit(1)

        print(f"[+] Local Hardhat node is running and healthy on {RPC_URL} (Chain 31337)")

    env["LOCAL_TEST_RPC"] = RPC_URL
    env["RUN_INTEGRATION_TESTS"] = "1"

    print("\n[*] Running test suite (Unit + Real EVM Integration)...")
    python_exe = sys.executable

    test_cmd = [python_exe, "-m", "unittest", "discover", "-s", "backend/tests", "-v"]

    try:
        res = subprocess.run(test_cmd, cwd=str(ROOT_DIR), env=env)
        exit_code = res.returncode
    finally:
        if started_node and node_process:
            print("\n[*] Stopping temporary Hardhat node...")
            node_process.terminate()
            try:
                node_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                node_process.kill()
            print("[+] Hardhat node stopped.")
        if node_log:
            node_log.close()

    if exit_code == 0:
        print("\n" + "=" * 70)
        print(" ALL INTEGRATION & UNIT TESTS PASSED SUCCESSFULLY! ")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print(" SOME TESTS FAILED. PLEASE CHECK OUTPUT ABOVE. ")
        print("=" * 70)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
