"""Submissions persistence; callers own transactions and commits."""

from sqlalchemy import select, update

from backend.db.rows import one
from backend.db.schema_v1 import approvals, attempts, proposals, receipts, send_locks
from backend.wallet_values import hashed, uid


def claim_pending_proposal(connection, now, proposal, proposal_id):
    return connection.execute(
        update(proposals)
        .where(
            proposals.c.id == proposal_id,
            proposals.c.status == "PENDING_REVIEW",
            proposals.c.version == proposal["version"],
            proposals.c.expires_at > now,
        )
        .values(status="AWAITING_SIGNATURE", version=proposals.c.version + 1)
    )


def insert_submission(connection, deployment_id, now, proposal_id, report_token, submission_id):
    return connection.execute(
        attempts.insert().values(
            id=submission_id,
            proposal_id=proposal_id,
            deployment_id=deployment_id,
            report_hash=hashed(report_token),
            report_expires_at=now + 86400,
            status="AWAITING_SIGNATURE",
            verification_status="UNVERIFIED",
            created_at=now,
            next_check_at=now + 15,
            lease_until=0,
        )
    )


def claim_send_lock(connection, deployment_id, principal, submission_id):
    return connection.execute(
        update(send_locks)
        .where(
            send_locks.c.wallet_id == principal.wallet_id,
            send_locks.c.deployment_id == deployment_id,
            send_locks.c.attempt_id.is_(None),
        )
        .values(attempt_id=submission_id)
    )


def insert_approval(connection, now, parameter_hash, principal, proposal_id):
    return connection.execute(
        approvals.insert().values(
            id=uid(),
            proposal_id=proposal_id,
            session_id=principal.session_id,
            action="APPROVE",
            parameter_hash=parameter_hash,
            created_at=now,
        )
    )


def find_submission(connection, submission_id):
    return one(connection, select(attempts).where(attempts.c.id == submission_id))


def record_reported_hash(connection, submission_id, tx_hash):
    return connection.execute(
        update(attempts)
        .where(attempts.c.id == submission_id)
        .values(tx_hash=tx_hash, next_check_at=0)
    )


def reject_signature(connection, submission_id):
    return connection.execute(
        update(attempts).where(attempts.c.id == submission_id).values(status="SIGNATURE_REJECTED")
    )


def reject_proposal_signature(connection, attempt):
    return connection.execute(
        update(proposals)
        .where(proposals.c.id == attempt["proposal_id"])
        .values(status="SIGNATURE_REJECTED")
    )


def release_send_lock(connection, submission_id):
    return connection.execute(
        update(send_locks).where(send_locks.c.attempt_id == submission_id).values(attempt_id=None)
    )


def mark_signature_unknown(connection, submission_id):
    return connection.execute(
        update(attempts)
        .where(attempts.c.id == submission_id, attempts.c.status == "AWAITING_SIGNATURE")
        .values(status="UNKNOWN", next_check_at=0)
    )


def find_owned_submission(connection, principal, submission_id):
    return one(
        connection,
        select(attempts)
        .join(proposals)
        .where(attempts.c.id == submission_id, proposals.c.wallet_id == principal.wallet_id),
    )


def record_recovered_hash(connection, submission_id, tx_hash):
    return connection.execute(
        update(attempts)
        .where(attempts.c.id == submission_id)
        .values(tx_hash=tx_hash.lower(), next_check_at=0, status="UNKNOWN")
    )


def transaction_history_query(principal):
    return (
        select(
            attempts.c.id,
            attempts.c.proposal_id,
            attempts.c.tx_hash,
            attempts.c.status,
            attempts.c.verification_status,
            attempts.c.created_at,
            proposals.c.operation,
            proposals.c.parameters,
            proposals.c.deployment_id,
            receipts.c.receipt_status,
            receipts.c.confirmations,
        )
        .join(proposals)
        .outerjoin(receipts, receipts.c.attempt_id == attempts.c.id)
        .where(proposals.c.wallet_id == principal.wallet_id)
    )
