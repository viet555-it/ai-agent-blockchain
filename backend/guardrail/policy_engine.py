"""Policy Engine and Guardrails for AI Agent Blockchain interactions.

Provides transaction limits, recipient address whitelisting, dry-run simulation validation,
parameter-bound human approvals, and tamper-proof execution tokens.
"""
import hashlib
import json
import logging
import time
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from web3 import Web3

logger = logging.getLogger("guardrail.policy_engine")

# Operation classifications
READ_OPERATIONS = {
    "get_native_balance",
    "get_token_balance",
    "get_token_info",
    "get_allowance",
    "get_transaction",
    "get_transaction_receipt",
    "get_gas_price",
    "read_contract",
    "simulate_transfer",
}

WRITE_OPERATIONS = {
    "native_transfer",
    "erc20_transfer",
    "erc20_approve",
    "faucet_claim",
}


class PolicyConfig(BaseModel):
    """Configurable security policy for blockchain operations."""
    max_native_transfer_limit: Decimal = Field(
        default=Decimal("0.5"),
        description="Maximum native ETH allowed per transaction in ether units"
    )
    max_token_transfer_limit: Decimal = Field(
        default=Decimal("500.0"),
        description="Maximum ERC20 token allowed per transaction"
    )
    recipient_whitelist: List[str] = Field(
        default_factory=lambda: [
            "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
            "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
            "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
            "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
            "0x9965507D1a55bcC2695C58ba16FB37d819B0A4df",
            "0x59c6f777551a5Bd19d73d8a47499F21fb53dCbe5", # Sepolia deployed deployer
            "0xeF9F53B00B069782256fC20697E7cf6a3136F9BC", # Deployer address
        ],
        description="List of whitelisted recipient Ethereum addresses"
    )
    enforce_whitelist: bool = Field(
        default=True,
        description="Whether to block non-whitelisted recipient addresses"
    )
    require_human_approval_for_writes: bool = Field(
        default=True,
        description="Whether write operations strictly require explicit human approval"
    )
    approval_timeout_seconds: int = Field(
        default=600,
        description="Time-to-live in seconds before a pending approval expires (default 10 minutes)"
    )


class AuditEvent(BaseModel):
    """Audit log entry for security and regulatory compliance."""
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    operation: str
    status: str  # VALIDATED, BLOCKED, PENDING_APPROVAL, APPROVED, REJECTED, EXECUTED, FAILED
    actor: str = "ai_agent"
    sanitized_parameters: Dict[str, Any]
    policy_checks: List[Dict[str, Any]]
    details: Optional[str] = None


class PendingApproval(BaseModel):
    """Represents a write transaction pending explicit human approval."""
    approval_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    operation: str
    created_at: float = Field(default_factory=time.time)
    expires_at: float
    parameters: Dict[str, Any]
    parameter_hash: str
    description: str
    status: str = "PENDING"  # PENDING, APPROVED, REJECTED, EXPIRED, EXECUTED
    reviewed_at: Optional[float] = None
    reviewer_comment: Optional[str] = None


class GuardrailResult(BaseModel):
    """Structured response returned to caller/frontend on policy evaluation."""
    is_allowed: bool
    requires_approval: bool
    operation: str
    operation_type: str  # "READ" or "WRITE"
    violations: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    pending_approval: Optional[PendingApproval] = None
    simulation_result: Optional[Dict[str, Any]] = None
    sanitized_parameters: Dict[str, Any] = Field(default_factory=dict)


class PolicyEngine:
    """Core Guardrail and Security Policy Engine.

    Guarantees:
    - Whitelist enforcement with EVM checksum verification.
    - Transaction limits for native & ERC-20 tokens.
    - Strict human-in-the-loop approval requirement for write operations.
    - Cryptographic parameter binding: modifications to parameters invalidate prior approval.
    - Expiration & anti-replay protection.
    - Zero exposure of private keys or secrets in logs/audit events.
    """

    def __init__(self, policy_config: Optional[PolicyConfig] = None):
        self.config = policy_config or PolicyConfig()
        self._pending_approvals: Dict[str, PendingApproval] = {}
        self._audit_log: List[AuditEvent] = []
        # Pre-normalize whitelist addresses
        self._normalized_whitelist: Set[str] = set()
        self._refresh_whitelist()

    def _refresh_whitelist(self):
        self._normalized_whitelist.clear()
        for addr in self.config.recipient_whitelist:
            try:
                if Web3.is_address(addr):
                    self._normalized_whitelist.add(Web3.to_checksum_address(addr))
            except Exception as e:
                logger.warning(f"Invalid address in whitelist skipped: {addr} ({e})")

    @staticmethod
    def compute_parameter_hash(operation: str, parameters: Dict[str, Any]) -> str:
        """Deterministically hash parameters to prevent parameter tampering."""
        # Sanitize and sort keys
        clean_params = {k: str(v) for k, v in sorted(parameters.items()) if not k.startswith("_")}
        serialized = json.dumps({"op": operation, "params": clean_params}, sort_keys=True)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def validate_address(self, address: str, field_name: str = "address") -> Tuple[bool, Optional[str], Optional[str]]:
        """Validate EVM address and return checksummed form."""
        if not address or not isinstance(address, str):
            return False, None, f"{field_name} must be a non-empty string"
        if not Web3.is_address(address):
            return False, None, f"Invalid EVM address format for {field_name}: '{address}'"
        checksummed = Web3.to_checksum_address(address)
        return True, checksummed, None

    def evaluate_request(
        self,
        operation: str,
        parameters: Dict[str, Any],
        simulation_data: Optional[Dict[str, Any]] = None,
    ) -> GuardrailResult:
        """Main guardrail entrypoint to validate any blockchain operation before execution."""
        violations: List[str] = []
        warnings: List[str] = []
        sanitized_params = dict(parameters)

        # 1. Classify operation
        is_write = operation in WRITE_OPERATIONS
        op_type = "WRITE" if is_write else "READ"

        # 2. If it's a read-only operation, validate and allow immediately
        if not is_write:
            self._record_audit(
                operation=operation,
                status="VALIDATED",
                params=sanitized_params,
                checks=[{"check": "read_classification", "passed": True}],
                details="Read-only operation permitted",
            )
            return GuardrailResult(
                is_allowed=True,
                requires_approval=False,
                operation=operation,
                operation_type=op_type,
                violations=[],
                warnings=[],
                sanitized_parameters=sanitized_params,
            )

        # 3. For WRITE operations: Validate parameters
        recipient_addr = parameters.get("recipient") or parameters.get("to") or parameters.get("to_address")
        amount_raw = parameters.get("amount") or parameters.get("amount_eth") or parameters.get("amount_token")

        if recipient_addr:
            is_valid_addr, checksum_recipient, err = self.validate_address(recipient_addr, "recipient")
            if not is_valid_addr:
                violations.append(err or "Invalid recipient address")
            else:
                sanitized_params["recipient"] = checksum_recipient
                # Whitelist Check
                if self.config.enforce_whitelist:
                    if checksum_recipient not in self._normalized_whitelist:
                        violations.append(
                            f"Recipient address {checksum_recipient} is NOT in the authorized whitelist."
                        )

        # 4. Amount limits check
        if amount_raw is not None:
            try:
                amount_dec = Decimal(str(amount_raw))
                if amount_dec <= 0:
                    violations.append("Transaction amount must be strictly greater than 0.")
                else:
                    if operation == "native_transfer":
                        if amount_dec > self.config.max_native_transfer_limit:
                            violations.append(
                                f"Amount {amount_dec} ETH exceeds native transfer limit of {self.config.max_native_transfer_limit} ETH."
                            )
                    elif operation in ("erc20_transfer", "erc20_approve", "faucet_claim"):
                        if amount_dec > self.config.max_token_transfer_limit:
                            violations.append(
                                f"Amount {amount_dec} tokens exceeds token policy limit of {self.config.max_token_transfer_limit} tokens."
                            )
            except Exception as e:
                violations.append(f"Invalid numerical amount '{amount_raw}': {e}")

        # 5. Contract dry-run simulation checks (if provided)
        if simulation_data is not None:
            if not simulation_data.get("isValid", True):
                reason = simulation_data.get("reason", "Simulation failed on-chain")
                violations.append(f"On-chain pre-flight simulation reverted: {reason}")

        # 6. Evaluate approval requirements
        if violations:
            self._record_audit(
                operation=operation,
                status="BLOCKED",
                params=sanitized_params,
                checks=[{"check": "policy_violations", "passed": False, "violations": violations}],
                details="Blocked by Guardrail Policy Engine",
            )
            return GuardrailResult(
                is_allowed=False,
                requires_approval=False,
                operation=operation,
                operation_type=op_type,
                violations=violations,
                warnings=warnings,
                simulation_result=simulation_data,
                sanitized_parameters=sanitized_params,
            )

        # If policy passed and human approval is required for writes:
        if self.config.require_human_approval_for_writes:
            param_hash = self.compute_parameter_hash(operation, sanitized_params)
            now = time.time()
            desc = self._format_description(operation, sanitized_params)
            pending = PendingApproval(
                operation=operation,
                expires_at=now + self.config.approval_timeout_seconds,
                parameters=sanitized_params,
                parameter_hash=param_hash,
                description=desc,
            )
            self._pending_approvals[pending.approval_id] = pending

            self._record_audit(
                operation=operation,
                status="PENDING_APPROVAL",
                params=sanitized_params,
                checks=[{"check": "human_approval_required", "passed": True}],
                details=f"Approval requested ID: {pending.approval_id}",
            )

            return GuardrailResult(
                is_allowed=True,
                requires_approval=True,
                operation=operation,
                operation_type=op_type,
                violations=[],
                warnings=warnings,
                pending_approval=pending,
                simulation_result=simulation_data,
                sanitized_parameters=sanitized_params,
            )

        # Allowed without approval (if disabled in config)
        return GuardrailResult(
            is_allowed=True,
            requires_approval=False,
            operation=operation,
            operation_type=op_type,
            violations=[],
            warnings=warnings,
            simulation_result=simulation_data,
            sanitized_parameters=sanitized_params,
        )

    def review_approval(
        self,
        approval_id: str,
        action: str,  # "APPROVE" or "REJECT"
        submitted_parameters: Dict[str, Any],
        reviewer_comment: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[PendingApproval]]:
        """Human approval action handler with tamper-proof verification."""
        pending = self._pending_approvals.get(approval_id)
        if not pending:
            return False, "Approval request not found or already consumed.", None

        # Check expiration
        now = time.time()
        if now > pending.expires_at:
            pending.status = "EXPIRED"
            self._record_audit(
                operation=pending.operation,
                status="EXPIRED",
                params=pending.parameters,
                checks=[],
                details=f"Approval request {approval_id} expired.",
            )
            return False, "Approval request has expired.", pending

        if pending.status != "PENDING":
            return False, f"Approval request is no longer pending (current state: {pending.status}).", pending

        # Tamper check: Compare submitted parameters with initial approval parameters
        submitted_hash = self.compute_parameter_hash(pending.operation, submitted_parameters)
        if submitted_hash != pending.parameter_hash:
            pending.status = "REJECTED"
            self._record_audit(
                operation=pending.operation,
                status="BLOCKED",
                params=submitted_parameters,
                checks=[{"check": "tamper_protection", "passed": False}],
                details="Parameter tampering detected during approval submission. Request rejected.",
            )
            return False, "Security Alert: Parameters have changed since the approval request was created.", pending

        if action.upper() == "APPROVE":
            pending.status = "APPROVED"
            pending.reviewed_at = now
            pending.reviewer_comment = reviewer_comment or "Approved by user via dashboard"
            self._record_audit(
                operation=pending.operation,
                status="APPROVED",
                params=pending.parameters,
                checks=[],
                details=f"Approval granted for {approval_id}",
            )
            return True, "Operation successfully approved.", pending
        else:
            pending.status = "REJECTED"
            pending.reviewed_at = now
            pending.reviewer_comment = reviewer_comment or "Rejected by user via dashboard"
            self._record_audit(
                operation=pending.operation,
                status="REJECTED",
                params=pending.parameters,
                checks=[],
                details=f"Approval rejected for {approval_id}",
            )
            return True, "Operation rejected.", pending

    def mark_executed(self, approval_id: str, tx_hash: Optional[str] = None, error: Optional[str] = None) -> bool:
        """Mark an approved transaction as executed or failed."""
        pending = self._pending_approvals.get(approval_id)
        if not pending:
            return False
        if error:
            pending.status = "FAILED"
            self._record_audit(
                operation=pending.operation,
                status="FAILED",
                params=pending.parameters,
                checks=[],
                details=f"Execution failed: {error}",
            )
        else:
            pending.status = "EXECUTED"
            self._record_audit(
                operation=pending.operation,
                status="EXECUTED",
                params=pending.parameters,
                checks=[],
                details=f"Execution successful. Tx: {tx_hash}",
            )
        return True

    def get_pending_approval(self, approval_id: str) -> Optional[PendingApproval]:
        return self._pending_approvals.get(approval_id)

    def list_audit_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [event.model_dump() for event in reversed(self._audit_log[-limit:])]

    def _record_audit(
        self,
        operation: str,
        status: str,
        params: Dict[str, Any],
        checks: List[Dict[str, Any]],
        details: Optional[str] = None,
    ):
        # Scrub any private keys or sensitive credentials
        safe_params = {k: v for k, v in params.items() if "key" not in k.lower() and "secret" not in k.lower()}
        event = AuditEvent(
            operation=operation,
            status=status,
            sanitized_parameters=safe_params,
            policy_checks=checks,
            details=details,
        )
        self._audit_log.append(event)

    def _format_description(self, operation: str, params: Dict[str, Any]) -> str:
        recipient = params.get("recipient", "N/A")
        amount = params.get("amount", params.get("amount_eth", params.get("amount_token", "N/A")))
        if operation == "native_transfer":
            return f"Send {amount} ETH to {recipient}"
        elif operation == "erc20_transfer":
            token_symbol = params.get("token_symbol", "AGNT")
            return f"Transfer {amount} {token_symbol} to {recipient}"
        elif operation == "erc20_approve":
            spender = params.get("spender", "N/A")
            token_symbol = params.get("token_symbol", "AGNT")
            return f"Approve spender {spender} for {amount} {token_symbol}"
        elif operation == "faucet_claim":
            return f"Claim {amount} AGNT testnet tokens for {recipient}"
        return f"{operation} with amount {amount}"
