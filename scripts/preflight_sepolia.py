"""Read-only Sepolia checks. Never signs or broadcasts; does not verify a signer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from web3 import Web3

from backend.token_amounts import format_token_units
from config.environment import PROJECT_ROOT, load_project_env

CHAIN_ID = 11155111

READ_RPC_METHODS = {
    "eth_blockNumber",
    "eth_chainId",
    "eth_getBlockByNumber",
    "eth_getBlockByHash",
    "eth_getCode",
    "eth_call",
    "eth_getBalance",
    "eth_getTransactionCount",
    "eth_gasPrice",
    "eth_maxPriorityFeePerGas",
    "eth_feeHistory",
    "eth_getTransactionReceipt",
    "eth_getTransactionByHash",
    "web3_clientVersion",
}


class ReadOnlyHTTPProvider(Web3.HTTPProvider):
    """Guard before Web3 builds/caches middleware request functions."""

    def __init__(self, endpoint_uri, **kwargs):
        super().__init__(endpoint_uri, exception_retry_configuration=None, **kwargs)
        self.methods = Counter()
        self.denied = []

    def make_request(self, method, params):
        self.methods[str(method)] += 1
        if method not in READ_RPC_METHODS:
            self.denied.append(str(method))
            raise RuntimeError("RPC method is not on the read-only allowlist")
        return super().make_request(method, params)


def api_read_smoke(w3, *, wallet: str, contract: str) -> dict:
    """Real API/RAG/RPC with scripted tool calls, guarded at the RPC transport."""
    import requests
    from fastapi.testclient import TestClient

    from agent.llm.base import LLMResponse, ToolCall
    from agent.llm.fake import FakeLLMProvider
    from backend.api.server import create_app
    from backend.services.blockchain_service import BlockchainService
    from config.settings import Settings

    session = requests.Session()
    provider = ReadOnlyHTTPProvider(
        w3.provider.endpoint_uri, session=session, request_kwargs={"timeout": 12}
    )
    w3 = Web3(provider)
    methods, denied = provider.methods, provider.denied
    try:
        nonce_before = w3.eth.get_transaction_count(wallet, "pending")
        llm = FakeLLMProvider(
            [
                LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="native", name="get_native_balance", arguments={"address": wallet}
                        ),
                        ToolCall(
                            id="token",
                            name="get_erc20_balance",
                            arguments={"wallet_address": wallet, "token_address": contract},
                        ),
                        ToolCall(
                            id="metadata",
                            name="get_token_info",
                            arguments={"token_address": contract},
                        ),
                    ]
                ),
                LLMResponse(content="Read complete."),
                LLMResponse(
                    tool_calls=[
                        ToolCall(
                            id="disabled-write",
                            name="transfer_eth",
                            arguments={"to": wallet, "value_eth": "0.000001"},
                        )
                    ]
                ),
                LLMResponse(content="Transfer completed."),
            ]
        )
        settings = Settings(
            _env_file=None,
            llm_provider="fake",
            wallet_private_key="",
            gemini_api_key="",
            anthropic_api_key="",
            openai_api_key="",
            dry_run=True,
        )
        service = BlockchainService(w3=w3, chain_id=CHAIN_ID)
        app = create_app(
            profile="sepolia_read",
            agent_mode="llm",
            enable_local_writes=False,
            blockchain=service,
            wallet=wallet,
            llm=llm,
            agent_settings=settings,
        )
        with TestClient(app) as client:
            response = client.post(
                "/api/chat",
                json={
                    "query": "Read ETH and AGNT balances and token metadata",
                    "session_id": "sepolia-read-preflight",
                },
            )
            if response.status_code != 200:
                raise RuntimeError("API read failed")
            read = response.json()
            if (
                read["error"]
                or read["requires_approval"]
                or read["blockchain_result"]["symbol"] != "AGNT"
            ):
                raise RuntimeError("API read result failed")
            successful = [
                step
                for step in read["timeline"]
                if step["name"] == "READ tool result" and step["status"] == "SUCCESS"
            ]
            if {row["tool_name"] for row in successful} != {
                "get_native_balance",
                "get_erc20_balance",
                "get_token_info",
            }:
                raise RuntimeError("Missing successful read tool")
            for row in successful:
                data = row["result"]["data"]
                if row["tool_name"] in {"get_native_balance", "get_erc20_balance"} and (
                    str(data["raw_balance"]) not in read["reply"]
                    or data["balance"] not in read["reply"]
                ):
                    raise RuntimeError("Displayed balance does not match RPC")
            probe = client.post(
                "/api/chat",
                json={
                    "query": "Try a transfer in read-only profile",
                    "session_id": "sepolia-read-preflight",
                },
            ).json()
            if not probe["error"] or probe["requires_approval"]:
                raise RuntimeError("Write probe was not blocked")
            scope = app.state.read_agent.retriever.scope
            rag_scope = {
                "chain_id": scope.chain_id,
                "contract_address": scope.contract_address,
                "abi_hash": scope.abi_hash,
            }
        nonce_after = w3.eth.get_transaction_count(wallet, "pending")
        if (
            nonce_before != nonce_after
            or denied
            or not methods["eth_call"]
            or not methods["eth_getBalance"]
        ):
            raise RuntimeError("Nonce changed or a forbidden RPC method was attempted")
        return {
            "status": "PASS",
            "llm": "fake; not a Gemini accuracy test",
            "rag": "real scoped index",
            "scope": rag_scope,
            "reply": read["reply"],
            "read_tools": [row["tool_name"] for row in successful],
            "write_tool_probe": "BLOCKED",
            "nonce_before": nonce_before,
            "nonce_after": nonce_after,
            "rpc_methods": dict(methods),
            "forbidden_rpc_attempts": denied,
            "broadcast_count": 0,
        }
    finally:
        session.close()


def preflight(root: Path, w3, *, wallet: str | None = None) -> dict:
    report = {
        "checked_at_utc": datetime.now(UTC).isoformat(),
        "mode": "read_only",
        "status": "FAIL",
        "checks": [],
        "facts": {},
        "write_authorized": False,
    }

    def require(name, observed, expected):
        passed = observed == expected
        report["checks"].append(
            {
                "name": name,
                "status": "PASS" if passed else "FAIL",
                "observed": observed,
                "expected": expected,
            }
        )
        if not passed:
            raise ValueError("Preflight gate failed")

    stage = "local_manifest"
    try:
        folder = root / "backend/abi/11155111"
        manifest = json.loads((folder / "deployment.json").read_text(encoding="utf-8"))
        abi_text = (folder / "AgentToken_abi.json").read_text(encoding="utf-8")
        abi = json.loads(abi_text)
        scope = json.loads((root / "knowledge/manifest.json").read_text(encoding="utf-8"))[
            "deployment_scope"
        ]
        address = Web3.to_checksum_address(manifest["contractAddress"])
        observer = Web3.to_checksum_address(wallet or manifest["deployer"])
        require("manifest_chain", str(manifest["chainId"]), str(CHAIN_ID))
        require("rag_chain", scope["chain_id"], CHAIN_ID)
        require("rag_contract", scope["contract_address"].lower(), address.lower())
        abi_hash = "sha256:" + hashlib.sha256(abi_text.encode()).hexdigest()
        require("rag_abi_hash", scope["abi_hash"], abi_hash)
        require("runtime_hash_present", bool(manifest.get("runtimeCodeHash")), True)
        report["facts"].update(
            contract=address,
            abi_hash=abi_hash,
            observed_wallet=observer,
            wallet_role="read-only observer; signer not verified",
            rag_doc_version=scope["doc_version"],
        )
        stage = "rpc_chain"
        require("rpc_chain", w3.eth.chain_id, CHAIN_ID)
        block = w3.eth.get_block("latest")
        height = block["number"]
        report["facts"].update(
            chain_id=CHAIN_ID,
            block_number=height,
            block_hash=Web3.to_hex(block["hash"]),
            block_timestamp=block["timestamp"],
        )
        stage = "runtime_bytecode"
        code = w3.eth.get_code(address, block_identifier=height)
        require("contract_code_present", bool(code), True)
        runtime_hash = Web3.to_hex(Web3.keccak(code))
        require(
            "runtime_code_hash",
            runtime_hash.lower().removeprefix("0x"),
            manifest["runtimeCodeHash"].lower().removeprefix("0x"),
        )
        report["facts"]["runtime_code_hash"] = runtime_hash
        stage = "contract_reads"
        contract = w3.eth.contract(address=address, abi=abi)

        def call(name, *args):
            return getattr(contract.functions, name)(*args).call(block_identifier=height)

        decimals = call("decimals")
        require("token_decimals", decimals, 18)
        symbol = call("symbol")
        require("token_symbol", symbol, "AGNT")
        facts = report["facts"]
        facts.update(
            token_name=call("name"),
            token_symbol=symbol,
            decimals=decimals,
            owner=call("owner"),
            total_supply_raw=str(call("totalSupply")),
            supply_cap_raw=str(call("cap")),
        )
        for getter, field in (
            ("maxTransferLimit", "max_transfer"),
            ("FAUCET_AMOUNT_LIMIT", "faucet_limit"),
        ):
            raw = call(getter)
            facts[field + "_raw"] = str(raw)
            facts[field + "_tokens"] = format_token_units(raw, decimals)
        facts["faucet_cooldown_seconds"] = call("faucetCooldown")
        last_claim = call("lastFaucetClaim", observer)
        facts["observer_last_claim"] = last_claim
        facts["observer_faucet_wait_seconds"] = max(
            0, last_claim + facts["faucet_cooldown_seconds"] - block["timestamp"]
        )
        token_balance = call("balanceOf", observer)
        facts["observer_token_balance_raw"] = str(token_balance)
        facts["observer_token_balance"] = format_token_units(token_balance, decimals)
        stage = "wallet_and_gas_reads"
        native = w3.eth.get_balance(observer, block_identifier=height)
        facts["observer_native_balance_wei"] = str(native)
        facts["observer_native_balance_eth"] = format_token_units(native, 18)
        facts["gas_price_wei"] = str(w3.eth.gas_price)
        facts["observer_pending_nonce"] = w3.eth.get_transaction_count(observer, "pending")
        report["status"] = "PASS"
        report["remaining_gates"] = [
            "Confirm testnet signer and recipient public addresses",
            "Approve transaction/fee caps and use of the designated wallet key",
            "Implement and test the Sepolia approval/execution profile; it remains locked",
        ]
    except Exception as error:
        # RPC exceptions can include the full URL/API credential. Never persist their text.
        report["failure"] = {"stage": stage, "type": type(error).__name__}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wallet", help="Public observer address; never a private key")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--api-smoke",
        action="store_true",
        help="Also test API + real RAG with FakeLLM and a read-only RPC guard",
    )
    args = parser.parse_args()
    load_project_env()
    rpc = os.environ.get("SEPOLIA_RPC_URL", "")
    if urlparse(rpc).scheme not in {"http", "https"}:
        raise SystemExit("Configure SEPOLIA_RPC_URL in the root .env")
    w3 = Web3(
        Web3.HTTPProvider(rpc, request_kwargs={"timeout": 12}, exception_retry_configuration=None)
    )
    report = preflight(
        PROJECT_ROOT, w3, wallet=args.wallet or os.environ.get("DEMO_WALLET_ADDRESS") or None
    )
    if args.api_smoke and report["status"] == "PASS":
        try:
            report["api_read_smoke"] = api_read_smoke(
                w3, wallet=report["facts"]["observed_wallet"], contract=report["facts"]["contract"]
            )
        except Exception as error:
            report["status"] = "FAIL"
            report["failure"] = {"stage": "api_read_smoke", "type": type(error).__name__}
    destination = args.output or PROJECT_ROOT / ".phase3" / (
        "sepolia-preflight-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))
    print(f"Evidence: {destination}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
