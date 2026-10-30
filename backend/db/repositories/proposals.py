"""Proposals persistence; callers own transactions and commits."""

import time

from sqlalchemy import select, update

from backend.db.rows import one
from backend.db.schema_v1 import (
    approvals,
    attempts,
    conversations,
    proposals,
    receipts,
    turns,
)
from backend.wallet_values import uid


def find_active_conversation(connection, deployment_id, principal, scope):
    return one(
        connection,
        select(conversations).where(
            conversations.c.id == scope["conversation_id"],
            conversations.c.wallet_id == principal.wallet_id,
            conversations.c.deployment_id == deployment_id,
            conversations.c.archived_at.is_(None),
        ),
    )


def find_processing_turn(connection, scope):
    return one(
        connection,
        select(turns).where(turns.c.id == scope["turn_id"], turns.c.status == "PROCESSING"),
    )


def insert_proposal(
    connection,
    *,
    decision,
    deployment_id,
    now,
    operation,
    parameters,
    pending,
    policy_hash,
    principal,
    scope,
    transaction,
):
    return connection.execute(
        proposals.insert().values(
            id=pending.approval_id,
            wallet_id=principal.wallet_id,
            conversation_id=scope["conversation_id"],
            turn_id=scope.get("turn_id"),
            context_id=scope["context_id"],
            deployment_id=deployment_id,
            operation=operation,
            parameters=parameters,
            transaction=transaction,
            parameter_hash=pending.parameter_hash,
            policy_hash=policy_hash,
            simulation=decision.simulation_result,
            status="PENDING_REVIEW",
            created_at=now,
            expires_at=pending.expires_at,
            version=0,
        )
    )


def find_owned_proposal(connection, principal, proposal_id):
    return one(
        connection,
        select(proposals).where(
            proposals.c.id == proposal_id, proposals.c.wallet_id == principal.wallet_id
        ),
    )


def expire_pending_proposal(connection, proposal_id):
    return connection.execute(
        update(proposals)
        .where(proposals.c.id == proposal_id, proposals.c.status == "PENDING_REVIEW")
        .values(status="EXPIRED")
    )


def proposal_attempts(connection, proposal_id):
    return connection.execute(
        select(attempts)
        .where(attempts.c.proposal_id == proposal_id)
        .order_by(attempts.c.created_at)
    )


def find_receipt(connection, row):
    return one(connection, select(receipts).where(receipts.c.attempt_id == row["id"]))


def reject_pending_proposal(connection, proposal_id):
    return connection.execute(
        update(proposals)
        .where(proposals.c.id == proposal_id, proposals.c.status == "PENDING_REVIEW")
        .values(status="REJECTED", version=proposals.c.version + 1)
    )


def insert_rejection(connection, parameter_hash, principal, proposal_id):
    return connection.execute(
        approvals.insert().values(
            id=uid(),
            proposal_id=proposal_id,
            session_id=principal.session_id,
            action="REJECT",
            parameter_hash=parameter_hash,
            created_at=time.time(),
        )
    )
