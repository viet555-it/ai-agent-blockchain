"""Reconciliation persistence; callers own transactions and commits."""

import time

from sqlalchemy import select, update

from backend.db.rows import one
from backend.db.schema_v1 import (
    attempts,
    proposals,
    receipts,
    send_locks,
)
from backend.wallet_values import hashed, token


def due_attempts(connection, deployment_id, now):
    return connection.execute(
        select(attempts.c.id)
        .where(
            attempts.c.deployment_id == deployment_id,
            attempts.c.status.in_(
                ["AWAITING_SIGNATURE", "UNKNOWN", "SUBMITTED", "MINED_SUCCESS", "MINED_REVERTED"]
            ),
            attempts.c.next_check_at <= now,
            attempts.c.lease_until < now,
        )
        .limit(20)
    )


def claim_lease(connection, attempt_id, lease, now):
    return connection.execute(
        update(attempts)
        .where(attempts.c.id == attempt_id, attempts.c.lease_until < now)
        .values(lease_until=now + 120, lease_id=lease)
    )


def find_attempt(connection, attempt_id):
    return one(connection, select(attempts).where(attempts.c.id == attempt_id))


def find_proposal(connection, attempt):
    return one(connection, select(proposals).where(proposals.c.id == attempt["proposal_id"]))


def release_failed_lease(connection, attempt_id, lease):
    return connection.execute(
        update(attempts)
        .where(attempts.c.id == attempt_id, attempts.c.lease_id == lease)
        .values(
            lease_until=0, lease_id=None, next_check_at=time.time() + 30, error_code="RPC_RETRY"
        )
    )


def find_leased_attempt(connection, attempt, lease):
    return one(
        connection,
        select(attempts).where(attempts.c.id == attempt["id"], attempts.c.lease_id == lease),
    )


def insert_replacement(connection, attempt, proposal, replacement_id, tx_hash):
    return connection.execute(
        attempts.insert().values(
            id=replacement_id,
            proposal_id=proposal["id"],
            deployment_id=attempt["deployment_id"],
            report_hash=hashed(token()),
            report_expires_at=time.time(),
            tx_hash=tx_hash,
            status="UNKNOWN",
            verification_status="UNVERIFIED",
            replaces_id=attempt["id"],
            created_at=time.time(),
            next_check_at=0,
            lease_until=0,
        )
    )


def mark_replaced(connection, attempt):
    return connection.execute(
        update(attempts)
        .where(attempts.c.id == attempt["id"])
        .values(status="REPLACED", lease_until=0, lease_id=None, last_checked_at=time.time())
    )


def delete_receipt(connection, attempt):
    return connection.execute(receipts.delete().where(receipts.c.attempt_id == attempt["id"]))


def transfer_send_lock(connection, attempt, replacement_id):
    return connection.execute(
        update(send_locks)
        .where(send_locks.c.attempt_id == attempt["id"])
        .values(attempt_id=replacement_id)
    )


def update_observation(connection, attempt, current, status, tx_hash, verification):
    return connection.execute(
        update(attempts)
        .where(attempts.c.id == attempt["id"])
        .values(
            tx_hash=tx_hash or current["tx_hash"],
            status=status,
            verification_status=verification,
            last_checked_at=time.time(),
            next_check_at=time.time() + (30 if status == "UNKNOWN" else 15),
            lease_id=None,
            lease_until=0,
            error_code=None,
        )
    )


def update_observed_proposal(connection, proposal, tx, verification):
    return connection.execute(
        update(proposals)
        .where(proposals.c.id == proposal["id"])
        .values(
            status="MISMATCHED"
            if verification == "MISMATCHED"
            else "SUBMITTED"
            if tx
            else "UNKNOWN"
        )
    )


def find_receipt(connection, attempt):
    return one(connection, select(receipts).where(receipts.c.attempt_id == attempt["id"]))


def update_receipt(connection, attempt, receipt_row):
    return connection.execute(
        update(receipts).where(receipts.c.attempt_id == attempt["id"]).values(**receipt_row)
    )


def insert_receipt(connection, receipt_row):
    return connection.execute(receipts.insert().values(**receipt_row))


def release_send_lock(connection, attempt):
    return connection.execute(
        update(send_locks).where(send_locks.c.attempt_id == attempt["id"]).values(attempt_id=None)
    )
