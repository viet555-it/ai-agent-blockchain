"""Approvals API endpoints."""

import asyncio

from fastapi import APIRouter, Header, HTTPException, Request

from backend.api.dependencies import legacy_only
from backend.api.schemas import ApprovalActionRequest, ProposalRequest
from backend.services.transaction_coordinator import TransactionError

router = APIRouter()


@router.get("/api/approval/{approval_id}")
def get_approval(
    request: Request,
    approval_id: str,
    session_id: str | None = Header(default=None, alias="X-Session-ID"),
):
    legacy_only(request)
    if request.app.state.transactions is not None:
        try:
            return request.app.state.transactions.get(approval_id, session_id or "")
        except TransactionError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from None
    pending = request.app.state.policy_engine.get_pending_approval(approval_id)
    if not pending:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return pending


@router.post("/api/approval/action")
async def handle_approval_action(request: Request, req: ApprovalActionRequest):
    legacy_only(request)
    if request.app.state.transactions is not None:
        try:
            return await asyncio.to_thread(
                request.app.state.transactions.review,
                req.approval_id,
                session_id=req.session_id or "",
                action=req.action,
                parameters=req.parameters,
                comment=req.reviewer_comment,
            )
        except TransactionError as error:
            raise HTTPException(status_code=error.status_code, detail=str(error)) from None
    if req.action.upper() != "REJECT":
        # G3.0 may prepare proposals, but never signs or fabricates an execution.
        raise HTTPException(
            status_code=403,
            detail="Execution is disabled in this integration profile; G3.2 is required",
        )
    ok, msg, pending = request.app.state.policy_engine.review_approval(
        approval_id=req.approval_id,
        action=req.action,
        submitted_parameters=req.parameters,
        reviewer_comment=req.reviewer_comment,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {
        "status": "REJECTED",
        "approval_id": req.approval_id,
        "message": "Transaction rejected by user.",
    }


@router.post("/api/transactions/propose")
async def propose_transaction(request: Request, req: ProposalRequest):
    legacy_only(request)
    if request.app.state.transactions is None:
        raise HTTPException(status_code=403, detail="Local transaction mode is disabled")
    try:
        return await asyncio.to_thread(
            request.app.state.transactions.propose,
            req.operation,
            amount=req.amount,
            session_id=req.session_id,
            recipient=req.recipient,
            token_address=req.token_address,
            actor_wallet=req.wallet_address,
        )
    except TransactionError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from None
    except Exception:
        raise HTTPException(
            status_code=503, detail="Local transaction preparation unavailable"
        ) from None
