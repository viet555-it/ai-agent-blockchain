"""One-command automated test runner for unit and live EVM integration tests.

Starts a local Hardhat node (if not already running), executes all tests,
and cleans up processes automatically.
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from web3 import Web3

ROOT_DIR = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = ROOT_DIR / "contracts"
RPC_URL = "http://127.0.0.1:8545"


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
    started_node = False

    if is_node_ready(RPC_URL):
        print(f"[+] Detected already running Hardhat node on {RPC_URL}")
    else:
        print(f"[*] Spawning local Hardhat node in {CONTRACTS_DIR}...")
        is_windows = sys.platform == "win32"
        npm_cmd = "npx.cmd" if is_windows else "npx"
        node_process = subprocess.Popen(
            [npm_cmd, "hardhat", "node"],
            cwd=str(CONTRACTS_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        started_node = True

        # Wait for node to initialize
        ready = False
        for _ in range(25):
            time.sleep(0.5)
            if is_node_ready(RPC_URL):
                ready = True
                break

        if not ready:
            print("[-] Error: Failed to start Hardhat local node within timeout.")
            if node_process:
                node_process.terminate()
            sys.exit(1)

        print(f"[+] Local Hardhat node is running and healthy on {RPC_URL} (Chain 31337)")

    env = os.environ.copy()
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
