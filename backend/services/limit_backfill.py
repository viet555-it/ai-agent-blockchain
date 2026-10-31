"""Offline adoption of stored browser-wallet transfers into the amount ledger.

Never infer block time from proposal/receipt creation time. Legacy uncertainty
remains RESERVED until authoritative reconciliation can resolve it.
"""

import re
from collections import Counter

from sqlalchemy import inspect, select

from backend.db.repositories import daily_limits as repository
from backend.db.schema_v1 import attempts, proposals, receipts
from backend.guardrail.policy_engine import PolicyEngine
from backend.services.daily_limits import LimitScope, amount_units, timestamp
from backend.services.transactions.serialization import digest
from backend.services.wallet_common import record_audit

VERIFIED_TIME = "_app_verified_block_timestamp"


def quantity(value):
    if isinstance(value, str) and re.fullmatch(r"0x[0-9a-fA-F]{1,64}", value):
        return amount_units(int(value, 16))
    return amount_units(value)


def transfer_scope(proposal):
    params, tx, operation = proposal["parameters"], proposal["transaction"], proposal["operation"]
    if PolicyEngine.compute_parameter_hash(operation, params) != proposal[
        "parameter_hash"
    ] or digest(tx) != params.get("payload_hash"):
        raise ValueError("PROPOSAL_INTEGRITY_MISMATCH")
    amount = amount_units(params["raw_amount"], positive=True)
    if operation == "native_transfer":
        if (
            quantity(tx["value"]) != amount
            or str(tx["to"]).lower() != str(params["recipient"]).lower()
        ):
            raise ValueError("NATIVE_AMOUNT_OR_RECIPIENT_MISMATCH")
        asset = "native"
    else:
        contract = params["contract_address"].lower()
        data = tx.get("data", "")
        if (
            quantity(tx["value"]) != 0
            or str(tx["to"]).lower() != contract
            or not isinstance(data, str)
            or not re.fullmatch(r"0xa9059cbb[0-9a-fA-F]{128}", data)
        ):
            raise ValueError("TOKEN_PAYLOAD_MISMATCH")
        encoded_recipient = "0x" + data[34:74]
        if (
            data[10:34] != "0" * 24
            or encoded_recipient.lower() != params["recipient"].lower()
            or int(data[74:], 16) != amount
        ):
            raise ValueError("TOKEN_AMOUNT_OR_RECIPIENT_MISMATCH")
        asset = "erc20:" + contract
    scope = LimitScope(proposal["wallet_id"], proposal["deployment_id"], asset)
    return scope.values(), amount


def final_evidence(proposal, history, receipt_rows, now):
    active = [row for row in history if row["status"] != "REPLACED"]
    if len(active) != 1:
        return "RESERVED", None, "UNRESOLVED_OR_MULTIPLE_ATTEMPTS"
    attempt = active[0]
    receipt = next((row for row in receipt_rows if row["attempt_id"] == attempt["id"]), None)
    if (
        attempt["status"] != "FINALIZED"
        or attempt["verification_status"] != "MATCHED"
        or receipt is None
        or receipt["finalized_at"] is None
    ):
        return "RESERVED", None, "FINALITY_OR_PAYLOAD_NOT_VERIFIED"
    data = receipt["data"]
    tx = proposal["transaction"]
    if (
        not attempt["tx_hash"]
        or str(data.get("transactionHash", "")).lower() != attempt["tx_hash"].lower()
        or str(data.get("blockHash", "")).lower() != receipt["block_hash"].lower()
        or str(data.get("from", "")).lower() != tx["from"].lower()
        or str(data.get("to", "")).lower() != tx["to"].lower()
        or quantity(data.get("status")) != receipt["receipt_status"]
        or quantity(data.get("blockNumber")) != receipt["block_number"]
    ):
        raise ValueError("RECEIPT_EVIDENCE_MISMATCH")
    if receipt["receipt_status"] == 0:
        return "REVERTED", None, "VERIFIED_FINAL_REVERT"
    if receipt["receipt_status"] != 1:
        raise ValueError("INVALID_RECEIPT_STATUS")
    if VERIFIED_TIME not in data:
        return "RESERVED", None, "LEGACY_SUCCESS_MISSING_VERIFIED_BLOCK_TIME"
    spent_at = timestamp(data[VERIFIED_TIME])
    if spent_at > now:
        raise ValueError("VERIFIED_BLOCK_TIME_IS_IN_FUTURE")
    return "SPENT", spent_at, "VERIFIED_FINAL_SUCCESS"


def build_plan(connection, *, now, wallet_id=None, deployment_id=None):
    now = timestamp(now)
    tables = set(inspect(connection).get_table_names())
    ledger_available = {"daily_limit_scopes", "daily_limit_entries"} <= tables
    query = (
        select(proposals)
        .where(
            proposals.c.operation.in_(["native_transfer", "erc20_transfer"]),
            select(attempts.c.id).where(attempts.c.proposal_id == proposals.c.id).exists(),
        )
        .order_by(proposals.c.id)
    )
    if wallet_id:
        query = query.where(proposals.c.wallet_id == wallet_id)
    if deployment_id:
        query = query.where(proposals.c.deployment_id == deployment_id)
    items, evidence = [], []
    for record in connection.execute(query).mappings():
        proposal = dict(record)
        history = [
            dict(row)
            for row in connection.execute(
                select(attempts)
                .where(attempts.c.proposal_id == proposal["id"])
                .order_by(attempts.c.id)
            ).mappings()
        ]
        receipt_rows = [
            dict(row)
            for row in connection.execute(
                select(receipts)
                .where(receipts.c.attempt_id.in_([row["id"] for row in history]))
                .order_by(receipts.c.id)
            ).mappings()
        ]
        existing = repository.find(connection, proposal["id"]) if ledger_available else None
        evidence.append(
            {
                "proposal": proposal,
                "attempts": history,
                "receipts": receipt_rows,
                "ledger": existing,
            }
        )
        item = {
            "proposal_id": proposal["id"],
            "wallet_id": proposal["wallet_id"],
            "deployment_id": proposal["deployment_id"],
        }
        try:
            scope, amount = transfer_scope(proposal)
            item.update(
                asset_id=scope["asset_id"],
                amount_base_units=str(amount),
                created_at=timestamp(min(row["created_at"] for row in history)),
            )
            if existing:
                if (
                    any(existing[key] != value for key, value in scope.items())
                    or int(existing["amount_base_units"]) != amount
                ):
                    raise ValueError("EXISTING_LEDGER_BINDING_MISMATCH")
                if existing["status"] == "RESERVED":
                    status, spent_at, reason = final_evidence(proposal, history, receipt_rows, now)
                    item.update(
                        action="SETTLE_" + status if status != "RESERVED" else "SKIP",
                        spent_at=spent_at,
                        reason=reason,
                        requires_chain_review=status == "RESERVED",
                    )
                else:
                    item.update(action="SKIP", reason="ALREADY_ACCOUNTED")
            else:
                status, spent_at, reason = final_evidence(proposal, history, receipt_rows, now)
                item.update(
                    action=status,
                    spent_at=spent_at,
                    reason=reason,
                    requires_chain_review=status == "RESERVED",
                )
        except (ValueError, KeyError, TypeError) as error:
            # Do not include raw parameters/receipts or capabilities in the preview.
            item.update(
                action="INVALID",
                reason=str(error) if isinstance(error, ValueError) else "MALFORMED_STORED_TRANSFER",
            )
        items.append(item)
    body = {
        "schema": "daily-limit-backfill-1",
        "as_of": now,
        "wallet_id": wallet_id,
        "deployment_id": deployment_id,
        "ledger_available": ledger_available,
        "source_evidence_sha256": digest(evidence),
        "items": items,
        "counts": dict(Counter(item["action"] for item in items)),
        "requires_chain_review": [
            item["proposal_id"] for item in items if item.get("requires_chain_review")
        ],
    }
    return {"plan_sha256": digest(body), "plan": body}


def apply_plan(connection, packet):
    """Acquire the SQLite writer lock; caller owns commit or rollback."""
    body = packet["plan"]
    if packet["plan_sha256"] != digest(body):
        raise ValueError("Backfill plan integrity mismatch")
    if not body["ledger_available"]:
        raise ValueError("Migrate the database before applying the backfill")
    if body["counts"].get("INVALID"):
        raise ValueError("Invalid historical records require review before applying")
    if connection.dialect.name != "sqlite":
        raise ValueError("Backfill currently supports SQLite only")
    # Lock before re-reading the snapshot, even when a caller uses a deferred transaction.
    connection.exec_driver_sql("UPDATE daily_limit_scopes SET version = version WHERE 0")
    current = build_plan(
        connection,
        now=body["as_of"],
        wallet_id=body["wallet_id"],
        deployment_id=body["deployment_id"],
    )
    if current != packet:
        raise ValueError("Database changed; generate a new backfill preview")
    imported = 0
    for item in body["items"]:
        if item["action"] == "SKIP":
            continue
        scope = {key: item[key] for key in ("wallet_id", "deployment_id", "asset_id")}
        repository.lock_scope(connection, scope)
        # Historical usage may exceed today's policy; never discard it to fit a new cap.
        status = item["action"].removeprefix("SETTLE_")
        if not item["action"].startswith("SETTLE_"):
            repository.reserve(
                connection,
                scope,
                item["proposal_id"],
                int(item["amount_base_units"]),
                item["created_at"],
            )
        if status != "RESERVED":
            repository.settle(connection, item["proposal_id"], status, item["spent_at"])
        record_audit(
            connection,
            item["wallet_id"],
            "LIMIT_BACKFILLED",
            item["proposal_id"],
            ledger_status=status,
            reason=item["reason"],
            plan_sha256=packet["plan_sha256"],
        )
        imported += 1
    return {
        "imported": imported,
        "requires_chain_review": body["requires_chain_review"],
        "plan_sha256": packet["plan_sha256"],
    }
