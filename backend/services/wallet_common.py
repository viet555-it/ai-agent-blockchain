"""Shared durable-wallet primitives."""

import time
from dataclasses import dataclass

from sqlalchemy import select, update

from backend.db.rows import one as one
from backend.db.schema_v1 import attempts, audit, contexts, proposals, sessions
from backend.wallet_errors import WalletErrorKind as ErrorKind
from backend.wallet_errors import fail as fail
from backend.wallet_values import hashed as hashed
from backend.wallet_values import token as token
from backend.wallet_values import uid as uid


def record_audit(connection, wallet_id, event_type, proposal_id=None, **data):
    connection.execute(
        audit.insert().values(
            id=uid(),
            wallet_id=wallet_id,
            proposal_id=proposal_id,
            event_type=event_type,
            data=data,
            created_at=time.time(),
        )
    )


def revoke_contexts(connection, session_id, context_id=None):
    predicate = contexts.c.session_id == session_id
    if context_id:
        predicate &= contexts.c.id == context_id
    ids = select(contexts.c.id).where(predicate)
    signing = select(proposals.c.id).where(
        proposals.c.context_id.in_(ids), proposals.c.status == "AWAITING_SIGNATURE"
    )
    connection.execute(
        update(attempts)
        .where(attempts.c.proposal_id.in_(signing), attempts.c.status == "AWAITING_SIGNATURE")
        .values(status="UNKNOWN")
    )
    connection.execute(
        update(proposals)
        .where(proposals.c.context_id.in_(ids), proposals.c.status == "AWAITING_SIGNATURE")
        .values(status="UNKNOWN", version=proposals.c.version + 1)
    )
    connection.execute(
        update(proposals)
        .where(proposals.c.context_id.in_(ids), proposals.c.status == "PENDING_REVIEW")
        .values(status="CANCELLED", version=proposals.c.version + 1)
    )
    connection.execute(
        update(contexts)
        .where(predicate)
        .values(revoked_at=time.time(), generation=contexts.c.generation + 1)
    )


@dataclass(frozen=True)
class Principal:
    session_id: str
    wallet_id: str
    address: str


def require_context(connection, principal, context_id, generation, deployment_id):
    now = time.time()
    context = one(
        connection,
        select(contexts)
        .join(sessions, contexts.c.session_id == sessions.c.id)
        .where(
            contexts.c.id == context_id,
            contexts.c.session_id == principal.session_id,
            contexts.c.revoked_at.is_(None),
            contexts.c.generation == generation,
            contexts.c.deployment_id == deployment_id,
            sessions.c.revoked_at.is_(None),
            sessions.c.expires_at > now,
        ),
    )
    if not context:
        fail(
            ErrorKind.CONFLICT,
            "STALE_CONTEXT",
            "Wallet context changed. Reconnect before continuing.",
        )
    return context
