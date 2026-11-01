"""Policy-only previews use the real ledger without granting or persisting actions."""

from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import SQLAlchemyError

from backend.db.schema_limits_v2 import metadata as limit_metadata
from backend.db.schema_v1 import metadata as wallet_metadata
from backend.db.store import Database
from backend.guardrail.policy_engine import PolicyConfig, PolicyEngine
from backend.services.daily_limits import DailyLimitService, LimitScope
from backend.services.guardrail_evaluation import evaluate_transfer_policy
from backend.token_amounts import UINT256_MAX, format_token_units
from eval.safety_v2.runner import load_dataset
from eval.safety_v2.runtime import SafetyRuntime, fixture_clock

NOW = 1_800_000_000
RECIPIENT = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
SCOPE = LimitScope("wallet-a", "deployment-a", "native")
TOKEN = "erc20:0x" + "12" * 20


@pytest.fixture
def db(tmp_path):
    current = Database("sqlite:///" + (tmp_path / "preview.db").as_posix())
    current.migrate()
    yield current
    current.close()


def config(**overrides):
    return PolicyConfig(recipient_whitelist=[RECIPIENT], **overrides)


def evaluate(db, amount=10**17, *, policy=None, **overrides):
    arguments = {
        "scope": SCOPE,
        "config": policy or config(),
        "operation": "native_transfer",
        "recipient": RECIPIENT,
        "amount_base_units": amount,
        "now": NOW,
    }
    arguments.update(overrides)
    with db.transaction() as connection:
        return evaluate_transfer_policy(connection, **arguments)


def seed(db, amount, *, identifier="pending", spent_at=None, scope=SCOPE):
    with db.transaction() as connection:
        service = DailyLimitService()
        assert service.reserve(
            connection,
            scope,
            identifier,
            amount,
            per_tx_limit=UINT256_MAX,
            daily_limit=UINT256_MAX,
            now=NOW - 100000,
        ).allowed
        if spent_at is not None:
            service.settle_success(connection, identifier, block_timestamp=spent_at, now=NOW)


def snapshot(db):
    with db.transaction() as connection:
        return {
            table.name: list(connection.execute(select(table)))
            for metadata in (wallet_metadata, limit_metadata)
            for table in metadata.sorted_tables
        }


def test_spent_and_reservations_leave_exact_threshold_and_one_wei_over(db):
    seed(db, 6 * 10**17, identifier="spent", spent_at=NOW - 60)
    seed(db, 3 * 10**17)
    exact = evaluate(db, policy_version=3)
    assert exact["decision"] == "REQUIRE_APPROVAL"
    assert exact["reason_code"] == "APP_APPROVAL_REQUIRED"
    assert exact["policy_version"] == 3
    assert exact["spent_base_units"] == "600000000000000000"
    assert exact["reserved_base_units"] == "300000000000000000"
    assert exact["remaining_base_units"] == "100000000000000000"
    assert exact["checks_scope"] == "policy_only"
    over = evaluate(db, 10**17 + 1)
    assert over["decision"] == "BLOCK"
    assert over["violations"] == ["DAILY_LIMIT_EXCEEDED"]


def test_per_transaction_and_daily_failures_have_stable_priority(db):
    seed(db, 9 * 10**17)
    result = evaluate(db, 5 * 10**17 + 1)
    assert result["reason_code"] == "PER_TX_LIMIT_EXCEEDED"
    assert result["violations"] == ["PER_TX_LIMIT_EXCEEDED", "DAILY_LIMIT_EXCEEDED"]


@pytest.mark.parametrize(
    "amount", [0, -1, True, 1.1, "1.0", "1e18", "NaN", "", " 1", str(UINT256_MAX + 1)]
)
def test_invalid_business_amount_returns_block_with_nullable_usage(db, amount):
    result = evaluate(db, amount)
    assert result["decision"] == "BLOCK" and result["reason_code"] == "INVALID_AMOUNT"
    assert result["requested_base_units"] is None
    assert result["remaining_base_units"] is None


@pytest.mark.parametrize(
    ("recipient", "code"),
    [(None, "INVALID_ADDRESS"), ("bad", "INVALID_ADDRESS"), ("0x" + "0" * 40, "ZERO_ADDRESS")],
)
def test_address_checks_match_actual_write_policy(db, recipient, code):
    policy = config(enforce_whitelist=False)
    preview = evaluate(db, recipient=recipient, policy=policy)
    actual = PolicyEngine(policy).evaluate_request(
        "native_transfer", {"recipient": recipient, "amount": "0.1"}, create_approval=False
    )
    assert preview["reason_code"] == code and not actual.is_allowed


def test_empty_whitelist_blocks_and_mixed_case_recipient_normalizes(db):
    empty = PolicyConfig(recipient_whitelist=[])
    assert evaluate(db, policy=empty)["reason_code"] == "RECIPIENT_NOT_ALLOWED"
    result = evaluate(db, recipient=RECIPIENT.lower())
    assert result["recipient"] == RECIPIENT
    assert result["decision"] == "REQUIRE_APPROVAL"


def test_disabled_app_approval_is_only_a_policy_decision(db):
    result = evaluate(db, policy=config(require_human_approval_for_writes=False))
    assert result["decision"] == "ALLOW" and result["reason_code"] == "POLICY_OK"
    assert result["checks_scope"] == "policy_only"
    assert result["policy_version"] is None
    assert not any(snapshot(db).values())


def test_repeated_previews_execute_only_reads_and_leave_all_wallet_state_unchanged(db):
    seed(db, 3 * 10**17)
    before = snapshot(db)
    statements = []

    def require_read(connection, cursor, statement, parameters, context, executemany):
        assert statement.lstrip().upper().startswith("SELECT")
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", require_read)
    try:
        for _ in range(3):
            assert evaluate(db)["decision"] == "REQUIRE_APPROVAL"
            assert evaluate(db, 10**18)["decision"] == "BLOCK"
            assert evaluate(db, recipient="bad")["decision"] == "BLOCK"
    finally:
        event.remove(db.engine, "before_cursor_execute", require_read)
    assert statements
    assert snapshot(db) == before


def test_token_preview_requires_trusted_deployment_metadata_and_exact_units(db):
    scope = LimitScope(SCOPE.wallet_id, SCOPE.deployment_id, TOKEN)
    arguments = {"scope": scope, "operation": "erc20_transfer"}
    missing = evaluate(db, "500000000", **arguments)
    assert missing["reason_code"] == "ASSET_POLICY_MISSING"
    assert missing["remaining_base_units"] is None
    exact = evaluate(db, "500000000", known_token_decimals={TOKEN: 6}, **arguments)
    assert exact["decision"] == "REQUIRE_APPROVAL"
    assert exact["per_tx_limit_base_units"] == "500000000"
    over = evaluate(db, "500000001", known_token_decimals={TOKEN: 6}, **arguments)
    assert over["reason_code"] == "PER_TX_LIMIT_EXCEEDED"
    with pytest.raises(ValueError, match="decimals"):
        evaluate(db, 1, known_token_decimals={TOKEN: True}, **arguments)


def test_uint256_precision_survives_json_string_response(db):
    maximum = Decimal(format_token_units(UINT256_MAX, 18))
    policy = config(max_native_transfer_limit=maximum, max_daily_native_transfer_limit=maximum)
    result = evaluate(db, str(UINT256_MAX), policy=policy)
    assert result["decision"] == "REQUIRE_APPROVAL"
    assert result["requested_base_units"] == str(UINT256_MAX)
    assert result["remaining_base_units"] == str(UINT256_MAX)


def test_window_boundary_keeps_old_pending_and_isolates_wallet_deployment_asset(db):
    seed(db, 6 * 10**17, identifier="old-spent", spent_at=NOW - 86400)
    seed(db, 3 * 10**17)
    assert evaluate(db)["spent_base_units"] == "0"
    assert evaluate(db)["reserved_base_units"] == "300000000000000000"
    for scope in (
        LimitScope("wallet-b", SCOPE.deployment_id, "native"),
        LimitScope(SCOPE.wallet_id, "deployment-b", "native"),
        LimitScope(SCOPE.wallet_id, SCOPE.deployment_id, TOKEN),
    ):
        result = evaluate(
            db,
            1,
            scope=scope,
            operation="native_transfer" if scope.asset_id == "native" else "erc20_transfer",
            known_token_decimals={TOKEN: 6},
        )
        assert result["reserved_base_units"] == "0"


def test_lowered_caps_do_not_free_existing_usage(db):
    seed(db, 8 * 10**17)
    result = evaluate(
        db,
        policy=config(
            max_native_transfer_limit=Decimal("0.5"),
            max_daily_native_transfer_limit=Decimal("0.5"),
        ),
    )
    assert result["reason_code"] == "DAILY_LIMIT_EXCEEDED"
    assert result["remaining_base_units"] == "0"
    assert result["reserved_base_units"] == "800000000000000000"


def test_policy_hash_changes_without_mutating_server_config(db):
    policy = config()
    original = policy.model_dump(mode="json")
    first = evaluate(db, policy=policy)
    evaluate(db, recipient="bad", policy=policy)
    assert policy.model_dump(mode="json") == original
    policy.max_daily_native_transfer_limit = Decimal("2")
    assert evaluate(db, policy=policy)["policy_hash"] != first["policy_hash"]
    with pytest.raises(ValueError, match="version"):
        evaluate(db, policy_version=True)


def test_infrastructure_and_invalid_server_config_are_not_successful_policy_blocks(db):
    invalid = config(max_native_transfer_limit=Decimal("2"))
    with pytest.raises(ValueError, match="Per-transaction"):
        evaluate(db, policy=invalid)
    with db.transaction() as connection:
        connection.exec_driver_sql("DROP TABLE daily_limit_entries")
    with pytest.raises(SQLAlchemyError):
        evaluate(db)


def test_unsupported_operations_and_asset_mismatch_fail_closed(db):
    assert evaluate(db, operation="erc20_approve")["reason_code"] == "UNSUPPORTED_OPERATION"
    assert evaluate(db, operation="erc20_transfer")["reason_code"] == "OPERATION_ASSET_MISMATCH"


@pytest.mark.parametrize(
    "identifier", ["V2-07", "V2-09", "V2-13", "V2-15", "V2-17", "V2-19", "V2-21", "V2-23"]
)
def test_preview_matches_real_wallet_preparation_on_fixed_benchmark_cases(tmp_path, identifier):
    case = next(row for row in load_dataset()[0] if row["id"] == identifier)
    runtime = SafetyRuntime(tmp_path / "wallet.db", case)
    fixture, request = case["fixture"], case["request"]
    try:
        before = snapshot(runtime.db)
        with runtime.db.transaction() as connection:
            result = evaluate_transfer_policy(
                connection,
                scope=LimitScope(
                    fixture["wallet_id"], fixture["deployment_id"], request["asset_id"]
                ),
                config=runtime.config,
                operation=request["operation"],
                recipient=request["recipient"],
                amount_base_units=request["amount_base_units"],
                now=fixture["now_utc_epoch"],
                known_token_decimals={
                    asset: data["decimals"]
                    for asset, data in fixture["assets"].items()
                    if asset != "native"
                },
                policy_version=fixture["policy_version"],
            )
        assert snapshot(runtime.db) == before
        assert result["decision"] == case["expected"]["policy_decision"]
        assert result["reason_code"] == case["expected"]["policy_reason"]
        with fixture_clock(fixture["now_utc_epoch"]):
            actual = runtime.prepare()
        assert actual.is_allowed == (result["decision"] != "BLOCK")
        assert bool(actual.pending_approval) == (result["decision"] == "REQUIRE_APPROVAL")
        assert runtime.broadcast_attempts == 0
    finally:
        runtime.close()
