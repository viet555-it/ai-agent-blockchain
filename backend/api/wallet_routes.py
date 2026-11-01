"""Authenticated browser-wallet/history API. Legacy demo endpoints remain separate."""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from web3 import Web3

from backend.db.repositories import guardrail_configs as gc_repo
from backend.db.schema_v1 import wallets
from backend.guardrail.policy_engine import PolicyEngine
from backend.services.browser_wallet import proposal_scope
from backend.services.daily_limits import DailyLimitService
from backend.services.wallet.limits import transfer_limit_request
from backend.services.wallet_common import fail, record_audit, require_context, revoke_contexts
from backend.token_amounts import format_token_units, to_token_units
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
    language: str | None = Field(default="auto", max_length=10)


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


class GuardrailConfigUpdate(Body):
    wallet_address: str = Field(min_length=42, max_length=42)
    per_tx_native_limit: float = Field(ge=0)
    daily_native_limit: float = Field(ge=0)
    token_limits: dict[str, Any] = Field(default_factory=dict)
    recipient_whitelist: list[str] = Field(default_factory=list)
    enforce_whitelist: bool = Field(default=False)
    require_app_approval: bool = Field(default=True)
    approval_timeout_seconds: int = Field(default=600, ge=10, le=86400)


class TestBlock(Body):
    wallet_address: str | None = Field(default=None, max_length=42)
    operation: str = Field(max_length=32)
    amount: str = Field(max_length=100)
    recipient: str | None = Field(default=None, max_length=42)
    token_address: str | None = Field(default=None, max_length=42)


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
                body.query,
                wallet=identity.address,
                session_id=conversation_id,
                language=body.language or "auto",
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
        runtime.clear_session(conversation_id)
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


# -------------------------------------------------------------------------
# GUARDRAIL MANAGEMENT & "THỬ CHẶN" (TEST-BLOCK) ENDPOINTS
# -------------------------------------------------------------------------


@router.get("/guardrail/config")
def get_guardrail_config(
    request: Request,
    wallet_address: str | None = None,
):
    state = request.app.state
    addr = wallet_address
    if not addr:
        try:
            identity = state.wallet_auth.principal(request)
            addr = identity.address
        except Exception:
            addr = None

    config = None
    wallet_id = None
    if addr and Web3.is_address(addr):
        addr = Web3.to_checksum_address(addr)
        try:
            with state.wallet_db.transaction() as connection:
                config = gc_repo.find_config(connection, addr)
                w_row = connection.execute(
                    select(wallets).where(wallets.c.address == addr)
                ).mappings().first()
                if w_row:
                    wallet_id = w_row["id"]
        except Exception:
            pass

    base_policy = state.policy_engine.config
    active_policy = gc_repo.row_to_policy_config(config, base_config=base_policy) if config else base_policy

    daily_native_spent = "0"
    daily_native_remaining = str(active_policy.max_daily_native_transfer_limit)
    daily_token_spent = "0"
    token_addr = None
    try:
        token_addr = state.browser_wallet.contract_address
    except Exception:
        pass
    token_per_tx = active_policy.get_per_tx_limit("erc20_transfer", token_addr)
    token_daily = active_policy.get_daily_limit("erc20_transfer", token_addr)
    daily_token_remaining = str(token_daily)

    if addr and wallet_id:
        try:
            deployment_id = state.browser_wallet.deployment()
            with state.wallet_db.transaction() as connection:
                native_req = transfer_limit_request(
                    wallet_id,
                    deployment_id,
                    "native_transfer",
                    {"raw_amount": 0},
                    active_policy,
                )
                if native_req:
                    native_eval = DailyLimitService.evaluate(connection, **native_req, now=time.time())
                    daily_native_spent = format_token_units(native_eval.spent, 18)
                    daily_native_remaining = format_token_units(native_eval.remaining, 18)

                token_req = transfer_limit_request(
                    wallet_id,
                    deployment_id,
                    "erc20_transfer",
                    {"raw_amount": 0, "contract_address": token_addr, "token_decimals": 18},
                    active_policy,
                )
                if token_req:
                    token_eval = DailyLimitService.evaluate(connection, **token_req, now=time.time())
                    daily_token_spent = format_token_units(token_eval.spent, 18)
                    daily_token_remaining = format_token_units(token_eval.remaining, 18)
        except Exception:
            pass

    return {
        "wallet_address": addr,
        "per_tx_native_limit": float(active_policy.max_native_transfer_limit),
        "daily_native_limit": float(active_policy.max_daily_native_transfer_limit),
        "daily_native_spent": daily_native_spent,
        "daily_native_remaining": daily_native_remaining,
        "token_address": token_addr,
        "per_tx_token_limit": float(token_per_tx),
        "daily_token_limit": float(token_daily),
        "daily_token_spent": daily_token_spent,
        "daily_token_remaining": daily_token_remaining,
        "token_limits": active_policy.token_limits,
        "recipient_whitelist": active_policy.recipient_whitelist,
        "enforce_whitelist": active_policy.enforce_whitelist,
        "require_app_approval": active_policy.require_human_approval_for_writes,
        "approval_timeout_seconds": active_policy.approval_timeout_seconds,
        "version": active_policy.version,
    }


@router.put("/guardrail/config")
def update_guardrail_config(
    body: GuardrailConfigUpdate,
    request: Request,
    identity=AUTHENTICATED,
):
    state = request.app.state
    if identity.address.lower() != body.wallet_address.lower():
        fail(
            ErrorKind.PERMISSION_DENIED,
            "FORBIDDEN",
            "You cannot modify guardrail settings for another wallet.",
        )

    valid_whitelist = []
    for w in body.recipient_whitelist:
        if w and isinstance(w, str) and Web3.is_address(w):
            valid_whitelist.append(Web3.to_checksum_address(w))

    now = time.time()
    with state.wallet_db.transaction() as connection:
        record = gc_repo.upsert_config(
            connection,
            wallet_address=identity.address,
            wallet_id=identity.wallet_id,
            per_tx_native_limit=Decimal(str(body.per_tx_native_limit)),
            daily_native_limit=Decimal(str(body.daily_native_limit)),
            token_limits=body.token_limits,
            recipient_whitelist=valid_whitelist,
            enforce_whitelist=body.enforce_whitelist,
            require_app_approval=body.require_app_approval,
            approval_timeout_seconds=body.approval_timeout_seconds,
            now=now,
        )
        record_audit(
            connection,
            identity.wallet_id,
            "GUARDRAIL_CONFIG_UPDATED",
            details=f"Updated version {record['version']}",
        )

    return {
        "status": "SAVED",
        "config": {
            "wallet_address": record["wallet_address"],
            "per_tx_native_limit": float(record["per_tx_native_limit"]),
            "daily_native_limit": float(record["daily_native_limit"]),
            "token_limits": record["token_limits"],
            "recipient_whitelist": record["recipient_whitelist"],
            "enforce_whitelist": record["enforce_whitelist"],
            "require_app_approval": record["require_app_approval"],
            "approval_timeout_seconds": record["approval_timeout_seconds"],
            "version": record["version"],
        },
    }


@router.post("/guardrail/test-block")
def test_block(
    body: TestBlock,
    request: Request,
):
    state = request.app.state
    target_wallet = body.wallet_address
    if not target_wallet:
        try:
            identity = state.wallet_auth.principal(request)
            target_wallet = identity.address
        except Exception:
            target_wallet = None

    policy_config = state.browser_wallet.proposals.get_wallet_policy_config(target_wallet)
    engine = PolicyEngine(policy_config)

    token_contract = (
        body.token_address
        or state.browser_wallet.contract_address
        or "0x0000000000000000000000000000000000000000"
    )
    native = body.operation == "native_transfer"
    decimals = 18

    parameters: dict[str, Any] = {
        "amount": body.amount,
        "recipient": body.recipient,
    }
    if not native:
        parameters["contract_address"] = token_contract
        parameters["token_decimals"] = decimals
        parameters["token_symbol"] = "AGNT"

    try:
        amount_dec = Decimal(str(body.amount))
        raw_amount = to_token_units(format(amount_dec, "f"), decimals)
        parameters["raw_amount"] = raw_amount
    except Exception:
        raw_amount = 0

    result = engine.evaluate_request(body.operation, parameters, None, create_approval=False)
    violations = list(result.violations)
    reason_code = "POLICY_ALLOWED"

    spent_str = "0"
    daily_limit_str = str(
        policy_config.get_daily_limit(body.operation, token_contract if not native else None)
    )
    remaining_str = daily_limit_str

    if target_wallet and Web3.is_address(target_wallet):
        try:
            target_addr = Web3.to_checksum_address(target_wallet)
            deployment_id = state.browser_wallet.deployment()
            with state.wallet_db.transaction() as connection:
                w_row = connection.execute(
                    select(wallets).where(wallets.c.address == target_addr)
                ).mappings().first()
                if w_row:
                    limit_req = transfer_limit_request(
                        w_row["id"], deployment_id, body.operation, parameters, policy_config
                    )
                    if limit_req:
                        limit_eval = DailyLimitService.evaluate(
                            connection, **limit_req, now=time.time()
                        )
                        spent_str = format_token_units(limit_eval.spent, decimals)
                        daily_limit_str = format_token_units(limit_req["daily_limit"], decimals)
                        remaining_str = format_token_units(limit_eval.remaining, decimals)
                        if not limit_eval.allowed:
                            violations.append(f"Vượt quá hạn mức 24h: {limit_eval.reason_code}")
                            reason_code = limit_eval.reason_code
        except Exception:
            pass

    if violations:
        decision = "BLOCK"
        is_allowed = False
        requires_approval = False
        reasons = violations
        if reason_code == "POLICY_ALLOWED":
            reason_code = "POLICY_VIOLATION"
    elif policy_config.require_human_approval_for_writes:
        decision = "REQUIRE_APPROVAL"
        is_allowed = True
        requires_approval = True
        reason_code = "REQUIRE_APP_APPROVAL"
        reasons = [
            "Giao dịch hợp lệ theo Guardrail và sẽ yêu cầu duyệt trên ứng dụng trước khi ký MetaMask."
        ]
    else:
        decision = "ALLOW"
        is_allowed = True
        requires_approval = False
        reason_code = "ALLOWED"
        reasons = ["Giao dịch hoàn toàn hợp lệ và được phép thực hiện."]

    per_tx_str = str(
        policy_config.get_per_tx_limit(body.operation, token_contract if not native else None)
    )

    return {
        "decision": decision,
        "is_allowed": is_allowed,
        "requires_approval": requires_approval,
        "reason_code": reason_code,
        "reasons": reasons,
        "details": {
            "operation": body.operation,
            "amount": body.amount,
            "recipient": body.recipient,
            "per_tx_limit": per_tx_str,
            "daily_limit": daily_limit_str,
            "daily_spent": spent_str,
            "daily_remaining": remaining_str,
            "enforce_whitelist": policy_config.enforce_whitelist,
            "require_app_approval": policy_config.require_human_approval_for_writes,
        },
    }
