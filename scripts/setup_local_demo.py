"""Deploy/reuse AgentToken on loopback Hardhat and export only chain 31337 artifacts."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from web3 import Web3

from config.environment import load_project_env

ROOT = Path(__file__).resolve().parents[1]


def setup(rpc: str) -> dict:
    url = urlparse(rpc)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("Only an HTTP loopback RPC without credentials is allowed")
    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 5}))
    if w3.eth.chain_id != 31337 or "hardhat" not in w3.client_version.lower():
        raise ValueError("Only a local Hardhat chain 31337 is allowed")
    artifact_path = ROOT / "contracts/artifacts/src/AgentToken.sol/AgentToken.json"
    if not artifact_path.exists():
        raise ValueError("Compile the contract first with npm run compile in contracts/")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    destination = ROOT / "backend/abi/31337"
    manifest_path = destination / "deployment.json"
    if manifest_path.exists():
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        address = saved.get("contractAddress")
        if saved.get("chainId") == "31337" and address and w3.eth.get_code(address):
            code_hash = Web3.to_hex(w3.keccak(w3.eth.get_code(address)))
            abi_path = destination / "AgentToken_abi.json"
            saved_abi = (
                json.loads(abi_path.read_text(encoding="utf-8")) if abi_path.exists() else None
            )
            if code_hash == saved.get("runtimeCodeHash") and saved_abi == artifact["abi"]:
                return {"status": "reused", **saved}
    sender = w3.eth.accounts[0]
    factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
    receipt = w3.eth.wait_for_transaction_receipt(
        factory.constructor(sender, 1_000_000).transact({"from": sender}), timeout=30
    )
    if receipt.status != 1:
        raise RuntimeError("Local deployment reverted")
    manifest = {
        "network": "hardhat-local",
        "chainId": "31337",
        "contractAddress": receipt.contractAddress,
        "deployer": sender,
        "initialSupply": "1000000",
        "deployedAt": datetime.now(UTC).isoformat(),
        "runtimeCodeHash": Web3.to_hex(w3.keccak(w3.eth.get_code(receipt.contractAddress))),
        "transactionHash": Web3.to_hex(receipt.transactionHash),
    }
    for folder in (destination, ROOT / "contracts/exported/31337"):
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "AgentToken_abi.json").write_text(
            json.dumps(artifact["abi"], indent=2), encoding="utf-8"
        )
        (folder / "deployment.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"status": "deployed", **manifest}


def main() -> None:
    load_project_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc", default=os.environ.get("LOCAL_RPC_URL", "http://127.0.0.1:8545"))
    args = parser.parse_args()
    print(json.dumps(setup(args.rpc), indent=2))


if __name__ == "__main__":
    main()
