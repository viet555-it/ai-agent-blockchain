"""Policy configuration, decisions and approval/audit records."""

import time
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class PolicyConfig(BaseModel):
    """Configurable security policy for blockchain operations."""

    wallet_address: str | None = Field(
        default=None, description="Optional wallet address bound to this configuration"
    )
    max_native_transfer_limit: Decimal = Field(
        default=Decimal("0.5"),
        description="Maximum native ETH allowed per transaction in ether units",
    )
    max_token_transfer_limit: Decimal = Field(
        default=Decimal("500.0"), description="Maximum ERC20 token allowed per transaction"
    )
    max_daily_native_transfer_limit: Decimal = Field(
        default=Decimal("1"),
        ge=0,
        allow_inf_nan=False,
        description="Maximum outgoing native amount in the rolling 24-hour window, excluding gas",
    )
    max_daily_token_transfer_limit: Decimal = Field(
        default=Decimal("1000"),
        ge=0,
        allow_inf_nan=False,
        description="Rolling 24-hour outgoing cap, accounted independently per ERC20 contract",
    )
    token_limits: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-token limits mapped by contract address or symbol",
    )
    recipient_whitelist: list[str] = Field(
        default_factory=lambda: [
            "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
            "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
            "0x9965507D1a55bcC2695C58ba16FB37d819B0A4df",
            "0x59c6f777551a5Bd19d73d8a47499F21fb53dCbe5",  # Sepolia deployed deployer
            "0xeF9F53B00B069782256fC20697E7cf6a3136F9BC",  # Deployer address
        ],
        description="List of whitelisted recipient Ethereum addresses",
    )
    enforce_whitelist: bool = Field(
        default=True, description="Whether to block non-whitelisted recipient addresses"
    )
    require_human_approval_for_writes: bool = Field(
        default=True,
        description="Whether write operations strictly require explicit human approval",
    )
    approval_timeout_seconds: int = Field(
        default=600,
        description="Time-to-live in seconds before a pending approval expires (default 10 minutes)",
    )
    version: int = Field(
        default=1, description="Configuration revision version number"
    )

    def get_per_tx_limit(self, operation: str, contract_address: str | None = None) -> Decimal:
        if operation == "native_transfer":
            return self.max_native_transfer_limit
        if contract_address:
            addr = contract_address.lower()
            if addr in self.token_limits:
                lim = self.token_limits[addr].get("per_tx_limit")
                if lim is not None:
                    return Decimal(str(lim))
            for k, v in self.token_limits.items():
                if isinstance(v, dict) and (k.lower() == addr or v.get("symbol", "").lower() == addr):
                    lim = v.get("per_tx_limit")
                    if lim is not None:
                        return Decimal(str(lim))
        return self.max_token_transfer_limit

    def get_daily_limit(self, operation: str, contract_address: str | None = None) -> Decimal:
        if operation == "native_transfer":
            return self.max_daily_native_transfer_limit
        if contract_address:
            addr = contract_address.lower()
            if addr in self.token_limits:
                lim = self.token_limits[addr].get("daily_limit")
                if lim is not None:
                    return Decimal(str(lim))
            for k, v in self.token_limits.items():
                if isinstance(v, dict) and (k.lower() == addr or v.get("symbol", "").lower() == addr):
                    lim = v.get("daily_limit")
                    if lim is not None:
                        return Decimal(str(lim))
        return self.max_daily_token_transfer_limit


class AuditEvent(BaseModel):
    """Audit log entry for security and regulatory compliance."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    operation: str
    status: str  # VALIDATED, BLOCKED, PENDING_APPROVAL, APPROVED, REJECTED, EXECUTED, FAILED
    actor: str = "ai_agent"
    sanitized_parameters: dict[str, Any]
    policy_checks: list[dict[str, Any]]
    details: str | None = None


class PendingApproval(BaseModel):
    """Represents a write transaction pending explicit human approval."""

    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operation: str
    created_at: float = Field(default_factory=time.time)
    expires_at: float
    parameters: dict[str, Any]
    parameter_hash: str
    description: str
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, EXPIRED, EXECUTED
    reviewed_at: float | None = None
    reviewer_comment: str | None = None
    tx_hash: str | None = None


class GuardrailResult(BaseModel):
    """Structured response returned to caller/frontend on policy evaluation."""

    is_allowed: bool
    requires_approval: bool
    operation: str
    operation_type: str  # "READ" or "WRITE"
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    pending_approval: PendingApproval | None = None
    simulation_result: dict[str, Any] | None = None
    sanitized_parameters: dict[str, Any] = Field(default_factory=dict)
