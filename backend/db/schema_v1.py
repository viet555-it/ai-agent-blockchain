"""Immutable schema for migration 0001. Future changes require a new migration."""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()


def table(name, *columns, **kwargs):
    return Table(name, metadata, Column("id", String(36), primary_key=True), *columns, **kwargs)


wallets = table(
    "wallet_identities",
    Column("address", String(42), unique=True, nullable=False),
    Column("created_at", Float, nullable=False),
)
challenges = table(
    "auth_challenges",
    Column("address", String(42), nullable=False),
    Column("message", Text, nullable=False),
    Column("binding_hash", String(64), nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("consumed_at", Float),
)
sessions = table(
    "auth_sessions",
    Column("wallet_id", ForeignKey(wallets.c.id), nullable=False),
    Column("token_hash", String(64), unique=True, nullable=False),
    Column("csrf_hash", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("revoked_at", Float),
)
deployments = table(
    "chain_deployments",
    Column("chain_id", Integer, nullable=False),
    Column("fingerprint", String(64), unique=True, nullable=False),
    Column("details", JSON, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("created_at", Float, nullable=False),
)
contexts = table(
    "wallet_contexts",
    Column("session_id", ForeignKey(sessions.c.id), nullable=False),
    Column("deployment_id", ForeignKey(deployments.c.id), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("revoked_at", Float),
)
conversations = table(
    "conversations",
    Column("wallet_id", ForeignKey(wallets.c.id), nullable=False),
    Column("deployment_id", ForeignKey(deployments.c.id), nullable=False),
    Column("title", String(120), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("archived_at", Float),
    Column("lease_id", String(36)),
    Column("lease_until", Float, nullable=False, default=0),
)
turns = table(
    "chat_turns",
    Column("conversation_id", ForeignKey(conversations.c.id), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("status", String(20), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("finished_at", Float),
    Column("response", JSON),
    Column("error_code", String(40)),
    UniqueConstraint("conversation_id", "request_id"),
    CheckConstraint("status IN ('PROCESSING','COMPLETED','FAILED','INTERRUPTED')"),
)
messages = table(
    "messages",
    Column("turn_id", ForeignKey(turns.c.id), nullable=False),
    Column("sequence", Integer, nullable=False),
    Column("role", String(16), nullable=False),
    Column("content", Text),
    Column("data", JSON, nullable=False),
    UniqueConstraint("turn_id", "sequence"),
)
proposals = table(
    "proposals",
    Column("wallet_id", ForeignKey(wallets.c.id), nullable=False),
    Column("conversation_id", ForeignKey(conversations.c.id)),
    Column("turn_id", ForeignKey(turns.c.id)),
    Column("context_id", ForeignKey(contexts.c.id), nullable=False),
    Column("deployment_id", ForeignKey(deployments.c.id), nullable=False),
    Column("operation", String(32), nullable=False),
    Column("parameters", JSON, nullable=False),
    Column("transaction", JSON, nullable=False),
    Column("parameter_hash", String(64), nullable=False),
    Column("policy_hash", String(64), nullable=False),
    Column("simulation", JSON, nullable=False),
    Column("status", String(32), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("version", Integer, nullable=False, default=0),
    CheckConstraint(
        "status IN ('PENDING_REVIEW','REJECTED','EXPIRED','CANCELLED','AWAITING_SIGNATURE','SUBMITTED','SIGNATURE_REJECTED','UNKNOWN','MISMATCHED')"
    ),
)
approvals = table(
    "approval_events",
    Column("proposal_id", ForeignKey(proposals.c.id), nullable=False),
    Column("session_id", ForeignKey(sessions.c.id), nullable=False),
    Column("action", String(24), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("parameter_hash", String(64), nullable=False),
)
attempts = table(
    "transaction_attempts",
    Column("proposal_id", ForeignKey(proposals.c.id), nullable=False),
    Column("deployment_id", ForeignKey(deployments.c.id), nullable=False),
    Column("report_hash", String(64), nullable=False),
    Column("report_expires_at", Float, nullable=False),
    Column("tx_hash", String(66)),
    Column("status", String(24), nullable=False),
    Column("verification_status", String(16), nullable=False),
    Column("replaces_id", ForeignKey("transaction_attempts.id")),
    Column("created_at", Float, nullable=False),
    Column("last_checked_at", Float),
    Column("next_check_at", Float, nullable=False),
    Column("lease_until", Float, nullable=False, default=0),
    Column("lease_id", String(36)),
    Column("error_code", String(40)),
    UniqueConstraint("deployment_id", "tx_hash"),
    CheckConstraint(
        "status IN ('AWAITING_SIGNATURE','SIGNATURE_REJECTED','UNKNOWN','SUBMITTED','MINED_SUCCESS','MINED_REVERTED','FINALIZED','REPLACED','DROPPED')"
    ),
    CheckConstraint("verification_status IN ('UNVERIFIED','MATCHED','MISMATCHED')"),
)
receipts = table(
    "transaction_receipts",
    Column("attempt_id", ForeignKey(attempts.c.id), unique=True, nullable=False),
    Column("block_number", Integer, nullable=False),
    Column("block_hash", String(66), nullable=False),
    Column("receipt_status", Integer, nullable=False),
    Column("confirmations", Integer, nullable=False),
    Column("data", JSON, nullable=False),
    Column("finalized_at", Float),
)
send_locks = table(
    "wallet_send_locks",
    Column("wallet_id", ForeignKey(wallets.c.id), nullable=False),
    Column("deployment_id", ForeignKey(deployments.c.id), nullable=False),
    Column("attempt_id", ForeignKey(attempts.c.id)),
    UniqueConstraint("wallet_id", "deployment_id"),
)
audit = table(
    "audit_events",
    Column("wallet_id", ForeignKey(wallets.c.id), nullable=False),
    Column("proposal_id", ForeignKey(proposals.c.id)),
    Column("event_type", String(48), nullable=False),
    Column("data", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
)
Index(
    "ix_conversations_owner",
    conversations.c.wallet_id,
    conversations.c.updated_at,
    conversations.c.id,
)
Index("ix_turns_conversation", turns.c.conversation_id, turns.c.created_at, turns.c.id)
Index("ix_proposals_owner", proposals.c.wallet_id, proposals.c.created_at, proposals.c.id)
Index("ix_attempts_poll", attempts.c.status, attempts.c.next_check_at)
Index("ix_audit_owner", audit.c.wallet_id, audit.c.created_at, audit.c.id)
