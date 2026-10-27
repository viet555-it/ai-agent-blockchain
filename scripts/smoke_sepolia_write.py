"""Execute only the two Sepolia fixtures explicitly authorized on 2026-10-27."""

from __future__ import annotations

import argparse
import json
import os
import time
from collections import Counter
from datetime import UTC, datetime

from eth_account import Account
from filelock import FileLock
from hexbytes import HexBytes
from web3 import Web3
from web3.logs import DISCARD

from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider
from backend.api.server import create_app
from backend.services.blockchain_service import BlockchainService
from backend.services.sepolia_execution import MAX_TOTAL_FEE_WEI, ExecutionLedger, SepoliaExecution
from backend.services.transaction_coordinator import digest, json_safe
from config.environment import PROJECT_ROOT, load_project_env
from config.settings import Settings
from scripts.preflight_sepolia import READ_RPC_METHODS, preflight

SENDER = Web3.to_checksum_address("0x59c6f777551a5Bd19d73d8a47499F21fb53dCbe5")
RECIPIENT = Web3.to_checksum_address("0xeF9F53B00B069782256fC20697E7cf6a3136F9BC")
CONTRACT = Web3.to_checksum_address("0xa453B71a492558C17efA82E294739e4eFef3C220")
LEDGER = PROJECT_ROOT / ".phase3/sepolia-approved-20261027-ledger.json"
REPORT = PROJECT_ROOT / ".phase3/sepolia-approved-20261027-results.json"


class ApprovedBatchProvider(Web3.HTTPProvider):
    def __init__(self, rpc, ledger):
        super().__init__(rpc, request_kwargs={"timeout": 15}, exception_retry_configuration=None)
        self.ledger = ledger
        self.methods = Counter()
        self.sent_hashes = set()

    def make_request(self, method, params):
        self.methods[str(method)] += 1
        if method not in READ_RPC_METHODS | {"eth_estimateGas", "eth_sendRawTransaction"}:
            raise RuntimeError("RPC method is not authorized for this batch")
        if method == "eth_sendRawTransaction":
            tx_hash = Web3.to_hex(Web3.keccak(HexBytes(params[0])))
            reserved = [
                row
                for row in self.ledger.snapshot()["reservations"].values()
                if row["tx_hash"] == tx_hash and row["status"] == "BROADCASTING"
            ]
            if len(reserved) != 1 or tx_hash in self.sent_hashes:
                raise RuntimeError("Raw transaction has no unique durable authorization")
            self.sent_hashes.add(tx_hash)
        return super().make_request(method, params)


def save(report):
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    temporary = REPORT.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(json_safe(report), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, REPORT)


def snapshot(w3, token, block="latest"):
    header = w3.eth.get_block(block)
    height = header["number"]
    return {
        "block": height,
        "sender_eth_wei": str(w3.eth.get_balance(SENDER, block_identifier=height)),
        "sender_agnt_raw": str(token.functions.balanceOf(SENDER).call(block_identifier=height)),
        "recipient_agnt_raw": str(
            token.functions.balanceOf(RECIPIENT).call(block_identifier=height)
        ),
    }


def resumable_rows(config, state, previous):
    """A resume reuses verified confirmed rows, never resets a reservation."""
    if digest(previous.get("grant")) != digest(config.public_grant):
        raise RuntimeError("Prior evidence has a different authorization")
    recovered = {}
    for operation, reservation in state["reservations"].items():
        if operation not in {"faucet_claim", "erc20_transfer"}:
            raise RuntimeError("Unknown fixture in the execution ledger")
        rows = [
            row
            for row in previous.get("cases", [])
            if row["operation"] == operation
            and row["status"] == "CONFIRMED"
            and row.get("tx_hash") == reservation["tx_hash"]
        ]
        if reservation["status"] != "CONFIRMED" or len(rows) != 1:
            raise RuntimeError("Existing broadcast must be reconciled before resuming")
        recovered[operation] = rows[0]
    return recovered


def observe_confirmations(w3, receipt):
    deadline = time.monotonic() + 90
    confirmations = w3.eth.block_number - receipt["blockNumber"] + 1
    while confirmations < 2 and time.monotonic() < deadline:
        time.sleep(3)
        confirmations = w3.eth.block_number - receipt["blockNumber"] + 1
    if (
        confirmations < 2
        or w3.eth.get_block(receipt["blockNumber"])["hash"] != receipt["blockHash"]
    ):
        raise RuntimeError("Two stable confirmations not observed")
    return confirmations


def execute(*, resume=False) -> dict:
    from fastapi.testclient import TestClient

    load_project_env()
    account = Account.from_key(os.environ.get("PRIVATE_KEY", ""))
    config = SepoliaExecution(SENDER, RECIPIENT, CONTRACT, LEDGER, account)
    ledger = ExecutionLedger(config)
    provider = ApprovedBatchProvider(os.environ["SEPOLIA_RPC_URL"], ledger)
    w3 = Web3(provider)
    report = {
        "started_at_utc": datetime.now(UTC).isoformat(),
        "status": "RUNNING",
        "grant": config.public_grant,
        "approval_mode": "automated harness; user explicitly approved two fixtures",
        "llm": "FakeLLM; no Gemini quality claim",
        "cases": [],
        "stage": "preflight",
    }
    # Refuse any pre-existing reservation: a new process must not silently get a new budget.
    state = ledger.snapshot()
    existing = state["reservations"]
    if existing and not resume:
        print(
            json.dumps(
                {
                    "status": "EXISTING_BATCH",
                    "ledger": str(LEDGER),
                    "transactions": existing,
                    "message": "Read/reconcile existing hashes; do not reexecute",
                }
            )
        )
        return {"status": "EXISTING_BATCH"}
    recovered = {}
    if existing:
        previous = json.loads(REPORT.read_text(encoding="utf-8"))
        if "rpc_runs" not in previous and "rpc_methods" in previous:
            previous["rpc_runs"] = [previous["rpc_methods"]]
        recovered = resumable_rows(config, state, previous)
        report = previous
        report["previous_run_status"] = report["status"]
        report["resumed_at_utc"] = datetime.now(UTC).isoformat()
        report["status"] = "RUNNING"
        report.pop("failure", None)
    new_transactions_expected = 2 - len(existing)
    report["stage"] = "preflight"
    save(report)
    try:
        baseline = preflight(PROJECT_ROOT, w3, wallet=SENDER)
        report["preflight"] = baseline
        if baseline["status"] != "PASS" or baseline["facts"]["contract"] != CONTRACT:
            raise RuntimeError("Preflight did not pass")
        service = BlockchainService(w3=w3, chain_id=11155111)
        abi, _ = service.network_manager.load_deployment_manifest(11155111)
        token = w3.eth.contract(address=CONTRACT, abi=abi)
        scripted = [
            LLMResponse(
                tool_calls=[ToolCall(id="faucet", name="faucet_claim", arguments={"amount": "10"})]
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="transfer",
                        name="transfer_erc20",
                        arguments={"to": RECIPIENT, "amount": "1", "token_address": CONTRACT},
                    )
                ]
            ),
        ]
        llm = FakeLLMProvider(
            ([] if "faucet_claim" in recovered else scripted[:1])
            + ([] if "erc20_transfer" in recovered else scripted[1:])
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
        app = create_app(
            profile="sepolia_write",
            agent_mode="llm",
            enable_local_writes=False,
            sepolia_execution=config,
            blockchain=service,
            wallet=SENDER,
            llm=llm,
            agent_settings=settings,
        )
        with TestClient(app) as client:
            fixtures = [
                (
                    "faucet_claim",
                    "Prepare a proposal to claim 10 AGNT from faucet for my wallet",
                    10 * 10**18,
                ),
                ("erc20_transfer", "Prepare a proposal to transfer 1 AGNT to " + RECIPIENT, 10**18),
            ]
            for operation, query, units in fixtures:
                if operation in recovered:
                    row = recovered[operation]
                    receipt = w3.eth.get_transaction_receipt(row["tx_hash"])
                    if (
                        receipt["status"] != 1
                        or receipt["from"].lower() != SENDER.lower()
                        or receipt["to"].lower() != CONTRACT.lower()
                        or Web3.to_hex(receipt["blockHash"]) != row["receipt"]["blockHash"]
                    ):
                        raise RuntimeError(
                            "Confirmed receipt changed; do not send another transaction"
                        )
                    report["stage"] = operation + ":resume-confirmations"
                    row["confirmations_observed"] = observe_confirmations(w3, receipt)
                    row["reused_confirmed_transaction"] = True
                    save(report)
                    continue
                report["stage"] = operation + ":proposal"
                before = snapshot(w3, token)
                nonce = w3.eth.get_transaction_count(SENDER, "pending")
                response = client.post(
                    "/api/chat",
                    json={
                        "query": query,
                        "session_id": "approved-sepolia-20261027",
                        "wallet_address": SENDER,
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError("Chat API failed")
                data = response.json()
                report["last_chat_result"] = data
                save(report)
                if data["error"] or not data["requires_approval"]:
                    raise RuntimeError("Expected bound proposal was not prepared")
                pending = data["guardrail_result"]["pending_approval"]
                if (
                    pending["operation"] != operation
                    or int(pending["parameters"]["raw_amount"]) != units
                ):
                    raise RuntimeError("Proposal differs from the approved fixture")
                if w3.eth.get_transaction_count(SENDER, "pending") != nonce:
                    raise RuntimeError("Nonce changed before approval")
                row = {
                    "operation": operation,
                    "status": "PREPARED",
                    "before": before,
                    "approval": pending,
                    "nonce_before_approval": nonce,
                }
                report["cases"].append(row)
                report["stage"] = operation + ":approval"
                save(report)
                response = client.post(
                    "/api/approval/action",
                    json={
                        "approval_id": pending["approval_id"],
                        "parameters": pending["parameters"],
                        "session_id": "approved-sepolia-20261027",
                        "action": "APPROVE",
                        "reviewer_comment": "Automated APPROVE for the exact two fixtures explicitly authorized by user on 2026-10-27",
                    },
                )
                if response.status_code != 200:
                    raise RuntimeError("Approval failed; inspect durable ledger before any retry")
                result = response.json()
                row["execution"] = result
                save(report)
                deadline = time.monotonic() + 90
                while result["status"] == "PENDING" and time.monotonic() < deadline:
                    time.sleep(3)
                    result = client.get(
                        "/api/approval/" + pending["approval_id"],
                        headers={"X-Session-ID": "approved-sepolia-20261027"},
                    ).json()
                    row["execution"] = result
                    save(report)
                if result["status"] != "CONFIRMED":
                    raise RuntimeError("Transaction is not confirmed; never blindly resend")
                receipt = w3.eth.get_transaction_receipt(result["tx_hash"])
                if (
                    receipt["status"] != 1
                    or receipt["from"].lower() != SENDER.lower()
                    or receipt["to"].lower() != CONTRACT.lower()
                ):
                    raise RuntimeError("Receipt identity/status mismatch")
                fee = receipt["gasUsed"] * receipt["effectiveGasPrice"]
                after = snapshot(w3, token, receipt["blockNumber"])
                expected_sender_delta = units if operation == "faucet_claim" else -units
                if (
                    int(after["sender_agnt_raw"]) - int(before["sender_agnt_raw"])
                    != expected_sender_delta
                ):
                    raise RuntimeError("Sender AGNT delta mismatch")
                expected_recipient_delta = 0 if operation == "faucet_claim" else units
                if (
                    int(after["recipient_agnt_raw"]) - int(before["recipient_agnt_raw"])
                    != expected_recipient_delta
                ):
                    raise RuntimeError("Recipient AGNT delta mismatch")
                if int(before["sender_eth_wei"]) - int(after["sender_eth_wei"]) != fee:
                    raise RuntimeError("Native balance delta does not equal receipt gas cost")
                events = token.events.Transfer().process_receipt(receipt, errors=DISCARD)
                expected_from = "0x" + "00" * 20 if operation == "faucet_claim" else SENDER
                expected_to = SENDER if operation == "faucet_claim" else RECIPIENT
                if not any(
                    event["args"]["from"].lower() == expected_from.lower()
                    and event["args"]["to"].lower() == expected_to.lower()
                    and event["args"]["value"] == units
                    for event in events
                ):
                    raise RuntimeError("Expected Transfer event missing")
                row.update(
                    status="CONFIRMED",
                    tx_hash=result["tx_hash"],
                    receipt=json_safe(dict(receipt)),
                    after=after,
                    actual_fee_wei=str(fee),
                    transfer_events=json_safe(list(events)),
                )
                report["stage"] = operation + ":confirmations"
                print(
                    json.dumps(
                        {
                            "operation": operation,
                            "status": "CONFIRMED",
                            "tx_hash": result["tx_hash"],
                            "fee_wei": str(fee),
                        }
                    ),
                    flush=True,
                )
                save(report)
                row["confirmations_observed"] = observe_confirmations(w3, receipt)
                save(report)
        report["total_fee_wei"] = str(sum(int(row["actual_fee_wei"]) for row in report["cases"]))
        if (
            int(report["total_fee_wei"]) > MAX_TOTAL_FEE_WEI
            or len(provider.sent_hashes) != new_transactions_expected
            or len(ledger.snapshot()["reservations"]) != 2
        ):
            raise RuntimeError("Batch fee/count mismatch")
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "FAIL_OR_NEEDS_RECONCILIATION"
        report["failure"] = {"type": type(error).__name__, "stage": report["stage"]}
    finally:
        report["finished_at_utc"] = datetime.now(UTC).isoformat()
        report.setdefault("rpc_runs", []).append(dict(provider.methods))
        report["rpc_methods"] = dict(provider.methods)
        report["ledger"] = ledger.snapshot()
        save(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-approved-batch", action="store_true")
    parser.add_argument(
        "--resume-approved-batch",
        action="store_true",
        help="Reuse confirmed receipts from the same ledger; never resend them",
    )
    args = parser.parse_args()
    if not args.execute_approved_batch:
        print(
            json.dumps(
                {
                    "mode": "preview",
                    "sender": SENDER,
                    "recipient": RECIPIENT,
                    "contract": CONTRACT,
                    "fixtures": ["faucet 10 AGNT", "transfer 1 AGNT"],
                    "max_total_fee_wei": str(MAX_TOTAL_FEE_WEI),
                }
            )
        )
        return 0
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(LEDGER) + ".run.lock", timeout=0):
        report = execute(resume=args.resume_approved_batch)
    print(json.dumps({"status": report["status"], "evidence": str(REPORT), "ledger": str(LEDGER)}))
    return 0 if report["status"] in {"PASS", "EXISTING_BATCH"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
