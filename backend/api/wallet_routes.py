"""Authenticated browser-wallet/history API. Legacy demo endpoints remain separate."""

import asyncio
import logging

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError

from backend.services.browser_wallet import proposal_scope
from backend.services.wallet_common import fail, require_context, revoke_contexts
from backend.wallet_errors import WalletErrorKind as ErrorKind

router = APIRouter(prefix="/api")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Challenge(Body):
    address: str = Field(max_length=42)
    chain_id: int


class Verify(Body):
    challenge_id: str = Field(max_length=36)
    signature: str = Field(max_length=1024)


class Context(Body):
    chain_id: int


class Conversation(Body):
    context_id: str = Field(max_length=36)
    generation: int
    title: str = Field(default="New chat", min_length=1, max_length=120)


class Edit(Body):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    archived: bool | None = None


class Turn(Body):
    query: str = Field(min_length=1, max_length=2000)
    context_id: str = Field(max_length=36)
    generation: int
    client_request_id: str = Field(min_length=1, max_length=128)


class Proposal(Body):
    conversation_id: str = Field(max_length=36)
    context_id: str = Field(max_length=36)
    generation: int
    operation: str = Field(max_length=32)
    amount: str = Field(max_length=100)
    recipient: str | None = Field(default=None, max_length=42)
    token_address: str | None = Field(default=None, max_length=42)


class Review(Body):
    parameter_hash: str = Field(min_length=64, max_length=64)
    context_id: str = Field(max_length=36)
    generation: int


class Report(Body):
    report_token: str = Field(min_length=20, max_length=128)
    tx_hash: str | None = Field(default=None, max_length=66)
    rejected: bool = False


class RecoverHash(Body):
    tx_hash: str = Field(min_length=66, max_length=66)


def principal(request: Request):
    return request.app.state.wallet_auth.principal(request)


AUTHENTICATED = Depends(principal)


@router.post("/auth/challenge")
def challenge(body: Challenge, request: Request, response: Response):
    return request.app.state.wallet_auth.challenge(request, response, body.address, body.chain_id)


@router.post("/auth/verify")
def verify(body: Verify, request: Request, response: Response):
    return request.app.state.wallet_auth.verify(
        request, response, body.challenge_id, body.signature
    )


@router.get("/auth/me")
def me(request: Request, identity=AUTHENTICATED):
    return {"address": identity.address, "chain_id": request.app.state.profile.chain_id}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    return request.app.state.wallet_auth.logout(request, response)


@router.post("/wallet-contexts")
def context(body: Context, request: Request, identity=AUTHENTICATED):
    return request.app.state.browser_wallet.create_context(identity, body.chain_id)


@router.post("/wallet-contexts/{context_id}/revoke")
def revoke(context_id: str, request: Request, identity=AUTHENTICATED):
    with request.app.state.wallet_db.transaction() as connection:
        revoke_contexts(connection, identity.session_id, context_id)
    return {"status": "REVOKED"}


@router.get("/history/conversations")
def list_conversations(
    request: Request,
    cursor: str | None = None,
    deployment_id: str | None = None,
    identity=AUTHENTICATED,
):
    return request.app.state.history.list(identity, cursor, deployment_id)


@router.post("/history/conversations")
def create_conversation(body: Conversation, request: Request, identity=AUTHENTICATED):
    state = request.app.state
    deployment_id = state.browser_wallet.deployment()
    with state.wallet_db.transaction() as connection:
        require_context(connection, identity, body.context_id, body.generation, deployment_id)
    return state.history.create(identity, deployment_id, body.title)


@router.patch("/history/conversations/{conversation_id}")
def edit_conversation(conversation_id: str, body: Edit, request: Request, identity=AUTHENTICATED):
    return request.app.state.history.edit(identity, conversation_id, body.title, body.archived)


@router.get("/history/conversations/{conversation_id}/messages")
def conversation_messages(
    conversation_id: str, request: Request, cursor: str | None = None, identity=AUTHENTICATED
):
    return request.app.state.history.list_turns(identity, conversation_id, cursor)


@router.get("/history/turns/{turn_id}")
def get_turn(turn_id: str, request: Request, identity=AUTHENTICATED):
    return request.app.state.history.turn(identity, turn_id)


@router.post("/history/conversations/{conversation_id}/turns")
async def chat(conversation_id: str, body: Turn, request: Request, identity=AUTHENTICATED):
    state = request.app.state
    state.wallet_auth.limiter.check(("chat", identity.wallet_id), limit=15)
    deployment_id = await asyncio.to_thread(state.browser_wallet.deployment)
    turn, created = await asyncio.to_thread(
        state.history.begin,
        identity,
        conversation_id,
        body.context_id,
        body.generation,
        deployment_id,
        body.client_request_id,
        body.query,
    )
    if not created:
        return {"turn_id": turn["id"], "status": turn["status"], "response": turn["response"]}
    runtime = state.history_runtime
    journal = []
    scope = proposal_scope.set(
        dict(
            principal=identity,
            context_id=body.context_id,
            generation=body.generation,
            conversation_id=conversation_id,
            turn_id=turn["id"],
        )
    )
    response = {
        "query": body.query,
        "reply": "Chat processing was interrupted. No transaction is automatically resent.",
        "intent": "error",
        "error": "CHAT_FAILED",
        "timeline": [],
    }
    try:
        previous = await asyncio.to_thread(
            state.history.context_messages, identity, conversation_id
        )
        runtime.service.restore_session(conversation_id, previous, observer=journal.append)
        async with asyncio.timeout(240):
            result = await runtime.process_message(
                body.query, wallet=identity.address, session_id=conversation_id
            )
        response = result.model_dump(mode="json")
    except Exception as error:
        # Do not expose exception text (RPC credentials/provider data).
        logging.getLogger(__name__).warning(
            "Wallet chat %s failed (%s)", turn["id"], type(error).__name__
        )
        response["error"] = "CHAT_FAILED"
    finally:
        proposal_scope.reset(scope)
        runtime.service.clear_session(conversation_id)
        runtime._locks.pop(conversation_id, None)
        await asyncio.to_thread(
            state.history.finish,
            identity,
            turn["id"],
            response,
            journal,
            bool(response.get("error")),
        )
    return {
        "turn_id": turn["id"],
        "status": "FAILED" if response.get("error") else "COMPLETED",
        "response": response,
    }


@router.post("/wallet-proposals")
def propose(body: Proposal, request: Request, identity=AUTHENTICATED):
    state = request.app.state
    with state.wallet_db.transaction() as connection:
        state.history.conversation(connection, identity, body.conversation_id)
    scope = dict(
        principal=identity,
        context_id=body.context_id,
        generation=body.generation,
        conversation_id=body.conversation_id,
    )
    return state.browser_wallet.prepare(
        scope, body.operation, body.amount, body.recipient, body.token_address
    )


@router.get("/wallet-proposals/{proposal_id}")
def get_proposal(proposal_id: str, request: Request, identity=AUTHENTICATED):
    return request.app.state.browser_wallet.get(identity, proposal_id)


@router.post("/wallet-proposals/{proposal_id}/reject")
def reject(proposal_id: str, body: Review, request: Request, identity=AUTHENTICATED):
    return request.app.state.browser_wallet.reject(identity, proposal_id, body.parameter_hash)


@router.post("/wallet-proposals/{proposal_id}/authorize")
def authorize(proposal_id: str, body: Review, request: Request, identity=AUTHENTICATED):
    return request.app.state.browser_wallet.authorize(
        identity, proposal_id, body.context_id, body.generation, body.parameter_hash
    )


@router.post("/wallet-submissions/{submission_id}/report")
def report(submission_id: str, body: Report, request: Request):
    # Write-only bearer capability, usable for a late A report after login switched to B.
    auth = request.app.state.wallet_auth
    auth.origin(request)
    auth.limiter.check(("report", request.client.host if request.client else "unknown"), limit=120)
    try:
        return request.app.state.browser_wallet.report(
            submission_id, body.report_token, body.tx_hash, body.rejected
        )
    except IntegrityError:
        fail(
            ErrorKind.CONFLICT,
            "TX_HASH",
            "This transaction is already associated with another submission.",
        )


@router.get("/history/transactions")
def transactions(request: Request, cursor: str | None = None, identity=AUTHENTICATED):
    return request.app.state.browser_wallet.list_transactions(identity, cursor)


@router.post("/wallet-submissions/{submission_id}/recover")
def recover_hash(submission_id: str, body: RecoverHash, request: Request, identity=AUTHENTICATED):
    try:
        return request.app.state.browser_wallet.recover_hash(identity, submission_id, body.tx_hash)
    except IntegrityError:
        fail(
            ErrorKind.CONFLICT,
            "TX_HASH",
            "This transaction is already associated with another submission.",
        )


@router.get("/history/transactions/{proposal_id}")
def transaction(proposal_id: str, request: Request, identity=AUTHENTICATED):
    return request.app.state.browser_wallet.get(identity, proposal_id)


@router.get("/history/audits")
def audits(request: Request, cursor: str | None = None, identity=AUTHENTICATED):
    return request.app.state.history.list_audit(identity, cursor)
