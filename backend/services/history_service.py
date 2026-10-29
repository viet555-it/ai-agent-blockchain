"""Owner-scoped history, durable chat leases and bounded context restoration."""

import base64
import time

from sqlalchemy import select, update

from backend.db.pagination import encode_cursor as encode_cursor
from backend.db.pagination import page as page
from backend.db.schema_v1 import audit, conversations, messages, proposals, turns
from backend.services.wallet_common import fail, one, record_audit, require_context, uid
from backend.wallet_errors import WalletErrorKind as ErrorKind


def protocol_json(value, decode=False):
    if isinstance(value, bytes):
        return {"$protocol_bytes": base64.b64encode(value).decode()}
    if isinstance(value, dict):
        if decode and set(value) == {"$protocol_bytes"}:
            return base64.b64decode(value["$protocol_bytes"])
        return {key: protocol_json(item, decode) for key, item in value.items()}
    if isinstance(value, list):
        return [protocol_json(item, decode) for item in value]
    return value


class HistoryService:
    def __init__(self, database):
        self.db = database

    def conversation(self, connection, principal, conversation_id):
        row = one(
            connection,
            select(conversations).where(
                conversations.c.id == conversation_id,
                conversations.c.wallet_id == principal.wallet_id,
            ),
        )
        if not row:
            fail(ErrorKind.NOT_FOUND, "NOT_FOUND", "Conversation not found.")
        return row

    def create(self, principal, deployment_id, title):
        now = time.time()
        row = dict(
            id=uid(),
            wallet_id=principal.wallet_id,
            deployment_id=deployment_id,
            title=title,
            created_at=now,
            updated_at=now,
            lease_until=0,
        )
        with self.db.transaction() as connection:
            connection.execute(conversations.insert().values(**row))
        return row

    def list(self, principal, cursor=None, deployment_id=None):
        with self.db.transaction() as connection:
            query = select(conversations).where(
                conversations.c.wallet_id == principal.wallet_id,
                conversations.c.archived_at.is_(None),
            )
            if deployment_id:
                query = query.where(conversations.c.deployment_id == deployment_id)
            return page(connection, query, conversations, conversations.c.updated_at, cursor)

    def edit(self, principal, conversation_id, title=None, archived=None):
        with self.db.transaction() as connection:
            self.conversation(connection, principal, conversation_id)
            values = {"updated_at": time.time()}
            if title is not None:
                values["title"] = title
            if archived is not None:
                values["archived_at"] = time.time() if archived else None
            connection.execute(
                update(conversations).where(conversations.c.id == conversation_id).values(**values)
            )
        return {"status": "UPDATED"}

    def list_turns(self, principal, conversation_id, cursor=None):
        with self.db.transaction() as connection:
            self.conversation(connection, principal, conversation_id)
            result = page(
                connection,
                select(turns).where(turns.c.conversation_id == conversation_id),
                turns,
                turns.c.created_at,
                cursor,
            )
            for turn in result["items"]:
                turn["messages"] = [
                    dict(row)
                    for row in connection.execute(
                        select(messages.c.role, messages.c.content)
                        .where(
                            messages.c.turn_id == turn["id"],
                            messages.c.role.in_(["user", "assistant"]),
                        )
                        .order_by(messages.c.sequence)
                    ).mappings()
                    if row["content"]
                ]
            return result

    def turn(self, principal, turn_id):
        with self.db.transaction() as connection:
            row = one(
                connection,
                select(turns)
                .join(conversations)
                .where(turns.c.id == turn_id, conversations.c.wallet_id == principal.wallet_id),
            )
        if not row:
            fail(ErrorKind.NOT_FOUND, "NOT_FOUND", "Chat turn not found.")
        return row

    def recover(self):
        now = time.time()
        with self.db.transaction() as connection:
            connection.execute(
                update(proposals)
                .where(proposals.c.status == "PENDING_REVIEW", proposals.c.expires_at <= now)
                .values(status="EXPIRED", version=proposals.c.version + 1)
            )
            stale = select(conversations.c.id).where(conversations.c.lease_until < now)
            connection.execute(
                update(turns)
                .where(turns.c.status == "PROCESSING", turns.c.conversation_id.in_(stale))
                .values(status="INTERRUPTED", finished_at=now, error_code="WORKER_INTERRUPTED")
            )

    def begin(
        self, principal, conversation_id, context_id, generation, deployment_id, request_id, query
    ):
        self.recover()
        now, turn_id = time.time(), uid()
        with self.db.transaction() as connection:
            require_context(connection, principal, context_id, generation, deployment_id)
            conversation = self.conversation(connection, principal, conversation_id)
            previous = one(
                connection,
                select(turns).where(
                    turns.c.conversation_id == conversation_id, turns.c.request_id == request_id
                ),
            )
            if previous:
                return previous, False
            if conversation["archived_at"] or conversation["deployment_id"] != deployment_id:
                fail(
                    ErrorKind.CONFLICT,
                    "CONVERSATION_CONTEXT",
                    "Start a conversation on the current deployment.",
                )
            claimed = connection.execute(
                update(conversations)
                .where(conversations.c.id == conversation_id, conversations.c.lease_until < now)
                .values(lease_until=now + 300, lease_id=turn_id, updated_at=now)
            )
            if claimed.rowcount != 1:
                fail(
                    ErrorKind.CONFLICT,
                    "CHAT_BUSY",
                    "Another message is being processed in this conversation.",
                )
            row = dict(
                id=turn_id,
                conversation_id=conversation_id,
                request_id=request_id,
                status="PROCESSING",
                created_at=now,
            )
            connection.execute(turns.insert().values(**row))
            connection.execute(
                messages.insert().values(
                    id=uid(),
                    turn_id=turn_id,
                    sequence=0,
                    role="user",
                    content=query,
                    data={"role": "user", "content": query},
                )
            )
        return row, True

    def context_messages(self, principal, conversation_id):
        with self.db.transaction() as connection:
            self.conversation(connection, principal, conversation_id)
            recent = list(
                connection.execute(
                    select(turns.c.id)
                    .where(
                        turns.c.conversation_id == conversation_id, turns.c.status == "COMPLETED"
                    )
                    .order_by(turns.c.created_at.desc(), turns.c.id.desc())
                    .limit(30)
                ).scalars()
            )
            result = []
            for turn_id in reversed(recent):
                result.extend(
                    connection.execute(
                        select(messages.c.data)
                        .where(messages.c.turn_id == turn_id)
                        .order_by(messages.c.sequence)
                    ).scalars()
                )
            return [protocol_json(message, decode=True) for message in result]

    def finish(self, principal, turn_id, response, journal, failed=False):
        with self.db.transaction() as connection:
            row = one(
                connection,
                select(turns)
                .join(conversations)
                .where(
                    turns.c.id == turn_id,
                    conversations.c.wallet_id == principal.wallet_id,
                    conversations.c.lease_id == turn_id,
                    turns.c.status == "PROCESSING",
                ),
            )
            if not row:
                fail(
                    ErrorKind.CONFLICT,
                    "CHAT_INTERRUPTED",
                    "Chat processing lease is no longer valid.",
                )
            # The user message was committed before the model ran. Preserve only
            # public user/final text and tool protocol; never persist thought text.
            sanitized = []
            for message in journal:
                message = dict(message)
                if message.get("role") == "user":
                    continue
                metadata = message.pop("provider_metadata", {})
                if message.get("tool_calls"):
                    message.pop("content", None)
                    # Keep opaque function-call signatures, never native thought text.
                    parts = [
                        {
                            key: part[key]
                            for key in ("function_call", "thought_signature")
                            if key in part
                        }
                        for part in metadata.get("parts", [])
                        if part.get("function_call")
                    ]
                    if metadata.get("provider") == "gemini" and parts:
                        message["provider_metadata"] = {"provider": "gemini", "parts": parts}
                sanitized.append(message)
            # The adapter may replace the model's proposal reply with a useful UI reply.
            if (
                sanitized
                and sanitized[-1].get("role") == "assistant"
                and not sanitized[-1].get("tool_calls")
            ):
                sanitized[-1]["content"] = response["reply"]
            else:
                sanitized.append({"role": "assistant", "content": response["reply"]})
            for sequence, message in enumerate(sanitized, 1):
                connection.execute(
                    messages.insert().values(
                        id=uid(),
                        turn_id=turn_id,
                        sequence=sequence,
                        role=message["role"],
                        content=message.get("content"),
                        data=protocol_json(message),
                    )
                )
            connection.execute(
                update(turns)
                .where(turns.c.id == turn_id)
                .values(
                    status="FAILED" if failed else "COMPLETED",
                    response=response,
                    finished_at=time.time(),
                    error_code=response.get("error"),
                )
            )
            connection.execute(
                update(conversations)
                .where(
                    conversations.c.id == row["conversation_id"],
                    conversations.c.lease_id == turn_id,
                )
                .values(lease_until=0, lease_id=None, updated_at=time.time())
            )
            record_audit(
                connection,
                principal.wallet_id,
                "CHAT_FAILED" if failed else "CHAT_COMPLETED",
                turn_id=turn_id,
            )

    def list_audit(self, principal, cursor=None):
        with self.db.transaction() as connection:
            return page(
                connection,
                select(audit).where(audit.c.wallet_id == principal.wallet_id),
                audit,
                audit.c.created_at,
                cursor,
            )
