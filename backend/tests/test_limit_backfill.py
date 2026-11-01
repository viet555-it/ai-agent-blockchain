"""Legacy ledger adoption is preview-only by default, exact and conservative about evidence."""

import copy
import json

import pytest
from sqlalchemy import select, update

from backend.db.schema_limits_v2 import entries
from backend.db.schema_v1 import attempts, audit, proposals, receipts
from backend.guardrail.policy_engine import PolicyEngine
from backend.services.daily_limits import DailyLimitService, LimitScope
from backend.services.limit_backfill import VERIFIED_TIME, apply_plan, build_plan
from eval.safety_v2.runner import load_dataset
from eval.safety_v2.runtime import SafetyRuntime
from scripts.backfill_daily_limits import execute

NOW = 1_800_000_000
HASH = "0x" + "ab" * 32
BLOCK = "0x" + "cd" * 32


@pytest.fixture
def runtime(tmp_path):
    case = next(case for case in load_dataset()[0] if case["id"] == "V2-07")
    current = SafetyRuntime(tmp_path / "legacy.db", case)
    yield current
    current.close()


def legacy(runtime, *, status="UNKNOWN", verified="UNVERIFIED", receipt_status=None, spent_at=None):
    pending = runtime.prepare().pending_approval
    runtime.authorize(pending)
    with runtime.db.transaction() as c:
        proposal = dict(
            c.execute(select(proposals).where(proposals.c.id == pending.approval_id))
            .mappings()
            .one()
        )
        attempt = dict(
            c.execute(select(attempts).where(attempts.c.proposal_id == pending.approval_id))
            .mappings()
            .one()
        )
        c.execute(entries.delete().where(entries.c.reservation_id == pending.approval_id))
        c.execute(
            update(attempts)
            .where(attempts.c.id == attempt["id"])
            .values(
                status=status, verification_status=verified, tx_hash=HASH, created_at=NOW - 1000
            )
        )
        if receipt_status is not None:
            data = {
                "transactionHash": HASH,
                "blockHash": BLOCK,
                "blockNumber": 10,
                "status": receipt_status,
                "from": proposal["transaction"]["from"],
                "to": proposal["transaction"]["to"],
            }
            if spent_at is not None:
                data[VERIFIED_TIME] = spent_at
            c.execute(
                receipts.insert().values(
                    id="fixture-receipt",
                    attempt_id=attempt["id"],
                    block_number=10,
                    block_hash=BLOCK,
                    receipt_status=receipt_status,
                    confirmations=1,
                    data=data,
                    finalized_at=NOW - 1 if status == "FINALIZED" else None,
                )
            )
    return pending.approval_id


def preview(runtime):
    with runtime.db.transaction() as c:
        return build_plan(c, now=NOW)


def apply(runtime, packet):
    with runtime.db.transaction() as c:
        return apply_plan(c, packet)


@pytest.mark.parametrize(
    "status", ["UNKNOWN", "SIGNATURE_REJECTED", "AWAITING_SIGNATURE", "DROPPED"]
)
def test_uncertain_attempts_are_reserved_not_freed_by_age(runtime, status):
    identifier = legacy(runtime, status=status)
    packet = preview(runtime)
    assert packet["plan"]["counts"] == {"RESERVED": 1}
    assert packet["plan"]["requires_chain_review"] == [identifier]
    assert apply(runtime, packet)["imported"] == 1
    with runtime.db.transaction() as c:
        row = c.execute(select(entries)).mappings().one()
        decision = DailyLimitService.evaluate(
            c,
            LimitScope(row["wallet_id"], row["deployment_id"], row["asset_id"]),
            1,
            per_tx_limit=10**18,
            daily_limit=10**18,
            now=NOW + 86400 * 30,
        )
        assert decision.reserved == 10**17


def test_final_success_without_verified_time_does_not_guess_from_creation_time(runtime):
    legacy(runtime, status="FINALIZED", verified="MATCHED", receipt_status=1)
    (item,) = preview(runtime)["plan"]["items"]
    assert item["action"] == "RESERVED" and item["spent_at"] is None
    assert item["reason"] == "LEGACY_SUCCESS_MISSING_VERIFIED_BLOCK_TIME"


@pytest.mark.parametrize("spent_at", [NOW - 60, NOW - 86400])
def test_verified_success_uses_exact_block_time_and_window(runtime, spent_at):
    legacy(runtime, status="FINALIZED", verified="MATCHED", receipt_status=1, spent_at=spent_at)
    apply(runtime, preview(runtime))
    with runtime.db.transaction() as c:
        row = c.execute(select(entries)).mappings().one()
        assert row["status"] == "SPENT" and row["spent_at"] == spent_at
        decision = DailyLimitService.evaluate(
            c,
            LimitScope(row["wallet_id"], row["deployment_id"], row["asset_id"]),
            1,
            per_tx_limit=10**18,
            daily_limit=10**18,
            now=NOW,
        )
        assert decision.spent == (10**17 if spent_at > NOW - 86400 else 0)


def test_only_verified_final_revert_releases_value(runtime):
    legacy(runtime, status="FINALIZED", verified="MATCHED", receipt_status=0)
    packet = preview(runtime)
    assert packet["plan"]["counts"] == {"REVERTED": 1}
    apply(runtime, packet)
    with runtime.db.transaction() as c:
        assert c.execute(select(entries.c.status)).scalar_one() == "REVERTED"
    assert preview(runtime)["plan"]["counts"] == {"SKIP": 1}


def test_nonfinal_and_mismatched_receipts_keep_reservation(runtime):
    legacy(runtime, status="MINED_REVERTED", verified="MATCHED", receipt_status=0)
    assert preview(runtime)["plan"]["counts"] == {"RESERVED": 1}
    with runtime.db.transaction() as c:
        c.execute(update(attempts).values(status="FINALIZED", verification_status="MISMATCHED"))
    assert preview(runtime)["plan"]["counts"] == {"RESERVED": 1}


def test_changed_snapshot_refuses_apply_without_partial_import(runtime):
    legacy(runtime)
    packet = preview(runtime)
    with runtime.db.transaction() as c:
        c.execute(update(attempts).values(status="SIGNATURE_REJECTED"))
    with pytest.raises(ValueError, match="Database changed"):
        apply(runtime, packet)
    with runtime.db.transaction() as c:
        assert list(c.execute(select(entries))) == []


def test_bad_integrity_or_receipt_rejects_entire_plan(runtime):
    identifier = legacy(
        runtime, status="FINALIZED", verified="MATCHED", receipt_status=1, spent_at=NOW - 1
    )
    with runtime.db.transaction() as c:
        data = dict(c.execute(select(receipts.c.data)).scalar_one())
        data["transactionHash"] = "0x" + "ff" * 32
        c.execute(update(receipts).values(data=data))
    packet = preview(runtime)
    assert packet["plan"]["counts"] == {"INVALID": 1}
    with pytest.raises(ValueError, match="Invalid historical"):
        apply(runtime, packet)
    with runtime.db.transaction() as c:
        c.execute(
            update(proposals).where(proposals.c.id == identifier).values(parameter_hash="0" * 64)
        )
    assert preview(runtime)["plan"]["items"][0]["reason"] == "PROPOSAL_INTEGRITY_MISMATCH"


def test_retry_preview_after_import_is_idempotent(runtime):
    legacy(runtime)
    assert apply(runtime, preview(runtime))["imported"] == 1
    assert apply(runtime, preview(runtime))["imported"] == 0
    assert len(preview(runtime)["plan"]["requires_chain_review"]) == 1
    with runtime.db.transaction() as c:
        assert len(list(c.execute(select(entries)))) == 1


def test_reserved_history_can_settle_after_authoritative_evidence_is_stored(runtime):
    legacy(runtime, status="FINALIZED", verified="MATCHED", receipt_status=1)
    apply(runtime, preview(runtime))
    with runtime.db.transaction() as c:
        data = dict(c.execute(select(receipts.c.data)).scalar_one())
        data[VERIFIED_TIME] = NOW - 60
        c.execute(update(receipts).values(data=data))
    packet = preview(runtime)
    assert packet["plan"]["counts"] == {"SETTLE_SPENT": 1}
    assert packet["plan"]["requires_chain_review"] == []
    apply(runtime, packet)
    with runtime.db.transaction() as c:
        assert c.execute(select(entries.c.status)).scalar_one() == "SPENT"
        events = list(
            c.execute(
                select(audit.c.data).where(audit.c.event_type == "LIMIT_BACKFILLED")
            ).scalars()
        )
        assert [event["ledger_status"] for event in events] == ["RESERVED", "SPENT"]


def test_import_failure_rolls_back_ledger_and_audit(runtime):
    from unittest.mock import patch

    legacy(runtime, status="FINALIZED", verified="MATCHED", receipt_status=0)
    packet = preview(runtime)
    with (
        patch(
            "backend.services.limit_backfill.repository.settle",
            side_effect=RuntimeError("storage failure"),
        ),
        pytest.raises(RuntimeError),
    ):
        apply(runtime, packet)
    with runtime.db.transaction() as c:
        assert list(c.execute(select(entries))) == []
        assert list(c.execute(select(audit).where(audit.c.event_type == "LIMIT_BACKFILLED"))) == []


def test_token_raw_units_import_without_decimals_or_float_rounding(tmp_path):
    case = copy.deepcopy(next(case for case in load_dataset()[0] if case["id"] == "V2-09"))
    current = SafetyRuntime(tmp_path / "token.db", case)
    try:
        identifier = legacy(current)
        with current.db.transaction() as c:
            parameters = dict(c.execute(select(proposals.c.parameters)).scalar_one())
            parameters.pop("token_decimals")
            c.execute(
                update(proposals).values(
                    parameters=parameters,
                    parameter_hash=PolicyEngine.compute_parameter_hash(
                        "erc20_transfer", parameters
                    ),
                )
            )
        packet = preview(current)
        (item,) = packet["plan"]["items"]
        assert item["asset_id"] == case["request"]["asset_id"]
        assert item["amount_base_units"] == case["request"]["amount_base_units"]
        apply(current, packet)
        with current.db.transaction() as c:
            assert c.execute(select(entries.c.reservation_id)).scalar_one() == identifier
    finally:
        current.close()


def test_cli_preview_is_read_only_and_apply_creates_backup(runtime, tmp_path):
    legacy(runtime)
    path = runtime.db.engine.url.database
    plan_path = tmp_path / "plan.json"
    execute(path, output=plan_path, now=NOW)
    with runtime.db.transaction() as c:
        assert list(c.execute(select(entries))) == []
    result = execute(
        path,
        output=tmp_path / "applied.json",
        plan_path=plan_path,
        backup_path=tmp_path / "backup.db",
    )
    assert result["imported"] == 1 and (tmp_path / "backup.db").is_file()
    assert json.loads(plan_path.read_text(encoding="utf-8"))["plan"]["counts"] == {"RESERVED": 1}


def test_dangerous_output_paths_and_plan_tampering_are_rejected(runtime, tmp_path):
    legacy(runtime)
    path = runtime.db.engine.url.database
    with pytest.raises(ValueError):
        execute(path, output=path)
    output = tmp_path / "output.json"
    with pytest.raises(ValueError):
        execute(path, output=output, plan_path=tmp_path / "plan.json", backup_path=output)
    packet = preview(runtime)
    packet["plan"]["items"][0]["amount_base_units"] = "1"
    with pytest.raises(ValueError, match="integrity"):
        apply(runtime, packet)


def test_replacement_history_counts_one_proposal_once(runtime):
    legacy(runtime, status="FINALIZED", verified="MATCHED", receipt_status=1, spent_at=NOW - 60)
    with runtime.db.transaction() as c:
        original = dict(c.execute(select(attempts)).mappings().one())
        replacement = {
            **original,
            "id": "replacement-attempt",
            "replaces_id": original["id"],
            "tx_hash": "0x" + "ef" * 32,
        }
        c.execute(update(attempts).where(attempts.c.id == original["id"]).values(status="REPLACED"))
        c.execute(attempts.insert().values(**replacement))
        data = dict(c.execute(select(receipts.c.data)).scalar_one())
        data["transactionHash"] = replacement["tx_hash"]
        c.execute(update(receipts).values(attempt_id=replacement["id"], data=data))
    packet = preview(runtime)
    assert packet["plan"]["counts"] == {"SPENT": 1}
    assert apply(runtime, packet)["imported"] == 1
    with runtime.db.transaction() as c:
        assert len(list(c.execute(select(entries)))) == 1


def test_preview_filters_and_apply_scope_cannot_silently_change(runtime, tmp_path):
    legacy(runtime)
    with runtime.db.transaction() as c:
        empty = build_plan(c, now=NOW, wallet_id="another-wallet")
    assert empty["plan"]["items"] == []
    plan_path = tmp_path / "plan.json"
    execute(runtime.db.engine.url.database, output=plan_path, now=NOW)
    with pytest.raises(ValueError, match="selectors"):
        execute(
            runtime.db.engine.url.database,
            output=tmp_path / "result.json",
            plan_path=plan_path,
            wallet_id="another-wallet",
            backup_path=tmp_path / "backup.db",
        )
    assert not (tmp_path / "backup.db").exists()
