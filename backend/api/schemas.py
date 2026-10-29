"""Request contracts shared by the API routes."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    query: str = Field(
        ..., min_length=1, max_length=2000, description="User prompt or blockchain command"
    )
    wallet_address: str | None = Field(
        default=None, description="Optional active wallet address"
    )
    session_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=128)


class ApprovalActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str
    action: Literal["APPROVE", "REJECT"]
    parameters: dict[str, Any] = Field(..., description="Exact parameters bound to this approval")
    reviewer_comment: str | None = None
    session_id: str | None = Field(default=None, min_length=1, max_length=128)


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["native_transfer", "erc20_transfer", "faucet_claim"]
    amount: str
    recipient: str | None = None
    token_address: str | None = None
    wallet_address: str | None = None
    session_id: str = Field(min_length=1, max_length=128)


class SwitchNetworkRequest(BaseModel):
    chain_id: int
