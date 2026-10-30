"""Deployments persistence; callers own transactions and commits."""

import time

from sqlalchemy import select, update

from backend.db.rows import one
from backend.db.schema_v1 import (
    contexts,
    deployments,
    send_locks,
)
from backend.wallet_values import uid


def find_fingerprint(connection, fingerprint):
    return one(connection, select(deployments).where(deployments.c.fingerprint == fingerprint))


def deactivate_other_deployments(connection, chain_id, fingerprint):
    return connection.execute(
        update(deployments)
        .where(deployments.c.chain_id == chain_id, deployments.c.fingerprint != fingerprint)
        .values(active=False)
    )


def activate_deployment(connection, found):
    return connection.execute(
        update(deployments).where(deployments.c.id == found["id"]).values(active=True)
    )


def insert_deployment(connection, chain_id, deployment_id, details, fingerprint):
    return connection.execute(
        deployments.insert().values(
            id=deployment_id,
            chain_id=chain_id,
            fingerprint=fingerprint,
            details=details,
            active=True,
            created_at=time.time(),
        )
    )


def insert_context(connection, context):
    return connection.execute(contexts.insert().values(**context))


def find_send_lock(connection, deployment_id, principal):
    return one(
        connection,
        select(send_locks).where(
            send_locks.c.wallet_id == principal.wallet_id,
            send_locks.c.deployment_id == deployment_id,
        ),
    )


def insert_send_lock(connection, deployment_id, principal):
    return connection.execute(
        send_locks.insert().values(
            id=uid(), wallet_id=principal.wallet_id, deployment_id=deployment_id
        )
    )
