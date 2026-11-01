"""Durability, exact base-unit accounting and races on real SQLite connections."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text

from backend.db.schema_limits_v2 import entries, scopes
from backend.db.store import ROOT, Database
from backend.services.daily_limits import DailyLimitService, LimitScope
from backend.token_amounts import UINT256_MAX, to_token_units

NOW = 1_800_000_000
SCOPE = LimitScope("wallet-a", "deployment-a", "native")
TOKEN = "erc20:0x" + "12" * 20


@pytest.fixture
def db(tmp_path):
    database = Database("sqlite:///" + (tmp_path / "limits.db").as_posix())
    database.migrate()
    yield database
    database.close()


def reserve(db, identifier, amount, *, scope=SCOPE, daily=100, per_tx=100, now=NOW):
    with db.transaction() as connection:
        return DailyLimitService().reserve(
            connection, scope, identifier, amount, per_tx_limit=per_tx, daily_limit=daily, now=now
        )


def evaluate(db, amount=1, *, scope=SCOPE, daily=100, per_tx=100, now=NOW):
    with db.transaction() as connection:
        return DailyLimitService.evaluate(
            connection, scope, amount, per_tx_limit=per_tx, daily_limit=daily, now=now
        )


def test_exact_threshold_then_one_base_unit_over(db):
    reserve(db, "first", 60)
    reserve(db, "second", 30)
    assert evaluate(db, 10).allowed
    assert evaluate(db, 11).reason_code == "DAILY_LIMIT_EXCEEDED"
    assert reserve(db, "third", 10).allowed
    assert not reserve(db, "fourth", 1).allowed
    assert evaluate(db).reserved == 100


def test_per_transaction_limit_and_zero_cap(db):
    assert not reserve(db, "over", 51, per_tx=50).allowed
    assert evaluate(db, per_tx=0, daily=0).reason_code == "PER_TX_LIMIT_EXCEEDED"
    with db.transaction() as connection:
        assert connection.execute(select(entries)).first() is None


def test_reads_do_not_create_scope_or_reservation(db):
    assert evaluate(db).remaining == 100
    with db.transaction() as connection:
        assert connection.execute(select(scopes)).first() is None
        assert connection.execute(select(entries)).first() is None


@pytest.mark.parametrize(
    "amount", [0, -1, 1.1, True, "NaN", "1e2", "1.0", " 1", "", str(UINT256_MAX + 1)]
)
def test_invalid_amount_rejected(db, amount):
    with pytest.raises(ValueError):
        reserve(db, "invalid", amount)
    assert evaluate(db).reserved == 0


def test_integer_precision_at_uint256_and_token_decimals(db):
    assert reserve(db, "max", str(UINT256_MAX), per_tx=UINT256_MAX, daily=UINT256_MAX).allowed
    assert evaluate(db, per_tx=UINT256_MAX, daily=UINT256_MAX).reserved == UINT256_MAX
    usdc = LimitScope("wallet-a", "deployment-a", TOKEN)
    amount = to_token_units("1.000001", 6)
    assert reserve(db, "usdc", amount, scope=usdc, per_tx=amount, daily=amount).allowed
    assert evaluate(db, scope=usdc, per_tx=amount, daily=amount).reserved == 1000001


@pytest.mark.parametrize(
    "other",
    [
        LimitScope("wallet-b", "deployment-a", "native"),
        LimitScope("wallet-a", "deployment-b", "native"),
        LimitScope("wallet-a", "deployment-a", TOKEN),
    ],
)
def test_scope_isolation(db, other):
    reserve(db, "original", 100)
    assert evaluate(db, scope=other).remaining == 100
    assert evaluate(db).remaining == 0


def test_success_idempotent_and_rolling_window_boundary(db):
    reserve(db, "tx", 80)
    service = DailyLimitService()
    with db.transaction() as connection:
        service.settle_success(connection, "tx", block_timestamp=NOW, now=NOW)
        service.settle_success(connection, "tx", block_timestamp=NOW, now=NOW)
    assert (evaluate(db).spent, evaluate(db).reserved) == (80, 0)
    assert evaluate(db, now=NOW + 86400 - 1).spent == 80
    assert evaluate(db, now=NOW + 86400).spent == 0


def test_unknown_reservation_does_not_expire(db):
    reserve(db, "unknown", 100)
    assert evaluate(db, now=NOW + 86400 * 3).reserved == 100
    assert not evaluate(db, now=NOW + 86400 * 3).allowed


def test_verified_revert_releases_once_and_conflicting_outcome_fails(db):
    reserve(db, "reverted", 100)
    with db.transaction() as connection:
        DailyLimitService().release_reverted(connection, "reverted")
        DailyLimitService().release_reverted(connection, "reverted")
    assert evaluate(db).remaining == 100
    with pytest.raises(ValueError), db.transaction() as connection:
        DailyLimitService().settle_success(connection, "reverted", block_timestamp=NOW, now=NOW)
    with pytest.raises(ValueError):
        reserve(db, "reverted", 100)


def test_retry_and_id_collision(db):
    reserve(db, "same", 70)
    assert reserve(db, "same", 70).reason_code == "ALREADY_RESERVED"
    assert evaluate(db).reserved == 70
    with pytest.raises(ValueError):
        reserve(db, "same", 71)
    with pytest.raises(ValueError):
        reserve(db, "same", 70, scope=LimitScope("wallet-b", "deployment-a", "native"))


def test_lowered_limit_preserves_reservations(db):
    reserve(db, "existing", 80)
    result = evaluate(db, daily=50, per_tx=50)
    assert (result.remaining, result.reserved, result.allowed) == (0, 80, False)


def test_reservation_joins_callers_transaction_rollback(db):
    with pytest.raises(RuntimeError), db.transaction() as connection:
        DailyLimitService().reserve(
            connection, SCOPE, "rollback", 100, per_tx_limit=100, daily_limit=100, now=NOW
        )
        raise RuntimeError("authorize/send lock failed")
    assert evaluate(db).remaining == 100


def test_restart_preserves_spent_and_pending(db):
    reserve(db, "spent", 60)
    with db.transaction() as connection:
        DailyLimitService().settle_success(connection, "spent", block_timestamp=NOW, now=NOW)
    reserve(db, "pending", 30)
    reopened = Database(str(db.engine.url))
    try:
        reopened.check_schema()
        result = evaluate(reopened)
        assert (result.spent, result.reserved, result.remaining) == (60, 30, 10)
    finally:
        reopened.close()


def test_concurrent_connections_cannot_overreserve(db):
    barrier = Barrier(2)

    def worker(identifier):
        barrier.wait(timeout=10)
        return reserve(db, identifier, 60).allowed

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(worker, ["a", "b"]))
    assert sorted(results) == [False, True]
    assert evaluate(db).reserved == 60


def test_concurrent_duplicate_settlement_does_not_double_spend(db):
    reserve(db, "tx", 60)
    barrier = Barrier(2)

    def worker(_):
        barrier.wait(timeout=10)
        with db.transaction() as connection:
            DailyLimitService().settle_success(connection, "tx", block_timestamp=NOW, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(worker, range(2)))
    assert (evaluate(db).spent, evaluate(db).reserved) == (60, 0)


def test_invalid_identity_limits_and_settlement_time(db):
    with pytest.raises(ValueError):
        evaluate(db, scope=LimitScope("", "deployment-a", "native"))
    with pytest.raises(ValueError):
        evaluate(db, daily=50, per_tx=100)
    with pytest.raises(ValueError):
        evaluate(db, now=float("nan"))
    reserve(db, "tx", 60)
    with pytest.raises(ValueError), db.transaction() as connection:
        DailyLimitService().settle_success(connection, "tx", block_timestamp=NOW + 1, now=NOW)
    assert evaluate(db).reserved == 60


def test_upgrade_existing_v1_database_keeps_history(tmp_path):
    database = Database("sqlite:///" + (tmp_path / "upgrade.db").as_posix())
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/db/migrations"))
    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "0001")
            connection.execute(
                text(
                    "INSERT INTO wallet_identities (id,address,created_at) VALUES ('owner','0x1111111111111111111111111111111111111111',0)"
                )
            )
        with pytest.raises(RuntimeError):
            database.check_schema()
        database.migrate()
        database.check_schema()
        with database.transaction() as connection:
            assert connection.execute(text("SELECT id FROM wallet_identities")).scalar() == "owner"
            assert "daily_limit_entries" in inspect(connection).get_table_names()
    finally:
        database.close()
