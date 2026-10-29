"""Policy Engine and Guardrails for AI Agent Blockchain interactions.

Provides transaction limits, recipient address whitelisting, dry-run simulation validation,
parameter-bound human approvals, and tamper-proof execution tokens.
"""

import logging
import threading
import time
from functools import wraps
from typing import Any

from web3 import Web3

from backend.guardrail.models import AuditEvent as AuditEvent
from backend.guardrail.models import GuardrailResult as GuardrailResult
from backend.guardrail.models import PendingApproval as PendingApproval
from backend.guardrail.models import PolicyConfig as PolicyConfig
from backend.guardrail.rules import READ_OPERATIONS as READ_OPERATIONS
from backend.guardrail.rules import WRITE_OPERATIONS as WRITE_OPERATIONS
from backend.guardrail.rules import (
    check_write_request,
    compute_parameter_hash,
    format_description,
    validate_address,
)

logger = logging.getLogger("guardrail.policy_engine")


def synchronized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


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

    def __init__(self, policy_config: PolicyConfig | None = None):
        self._lock = threading.RLock()
        self.config = policy_config or PolicyConfig()
        self._pending_approvals: dict[str, PendingApproval] = {}
        self._audit_log: list[AuditEvent] = []
        # Pre-normalize whitelist addresses
        self._normalized_whitelist: set[str] = set()
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
    def compute_parameter_hash(operation: str, parameters: dict[str, Any]) -> str:
        return compute_parameter_hash(operation, parameters)

    def validate_address(
        self, address: str, field_name: str = "address"
    ) -> tuple[bool, str | None, str | None]:
        return validate_address(address, field_name)

    @synchronized
    def evaluate_request(
        self,
        operation: str,
        parameters: dict[str, Any],
        simulation_data: dict[str, Any] | None = None,
        *,
        create_approval: bool = True,
    ) -> GuardrailResult:
        """Main guardrail entrypoint to validate any blockchain operation before execution."""
        violations: list[str] = []
        warnings: list[str] = []
        sanitized_params = dict(parameters)

        # 1. Classify operation
        is_write = operation in WRITE_OPERATIONS
        op_type = "WRITE" if is_write else "READ"
        if operation not in READ_OPERATIONS | WRITE_OPERATIONS:
            return GuardrailResult(
                is_allowed=False,
                requires_approval=False,
                operation=operation,
                operation_type="UNKNOWN",
                violations=["Unsupported operation"],
                sanitized_parameters=sanitized_params,
            )

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

        sanitized_params, violations = check_write_request(
            operation,
            parameters,
            simulation_data,
            self.config,
            self._normalized_whitelist,
            address_validator=self.validate_address,
        )

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
        if create_approval and self.config.require_human_approval_for_writes:
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

    @synchronized
    def review_approval(
        self,
        approval_id: str,
        action: str,  # "APPROVE" or "REJECT"
        submitted_parameters: dict[str, Any],
        reviewer_comment: str | None = None,
    ) -> tuple[bool, str, PendingApproval | None]:
        """Human approval action handler with tamper-proof verification."""
        if action.upper() not in {"APPROVE", "REJECT"}:
            return False, "Unknown approval action.", None
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
            return (
                False,
                f"Approval request is no longer pending (current state: {pending.status}).",
                pending,
            )

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
            return (
                False,
                "Security Alert: Parameters have changed since the approval request was created.",
                pending,
            )

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

    @synchronized
    def mark_executed(
        self, approval_id: str, tx_hash: str | None = None, error: str | None = None
    ) -> bool:
        """Mark an approved transaction as executed or failed."""
        pending = self._pending_approvals.get(approval_id)
        if not pending:
            return False
        if pending.status not in {"APPROVED", "SUBMITTED"}:
            return False
        pending.tx_hash = tx_hash or pending.tx_hash
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

    def get_pending_approval(self, approval_id: str) -> PendingApproval | None:
        return self._pending_approvals.get(approval_id)

    def list_audit_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return [event.model_dump() for event in reversed(self._audit_log[-limit:])]

    def _record_audit(
        self,
        operation: str,
        status: str,
        params: dict[str, Any],
        checks: list[dict[str, Any]],
        details: str | None = None,
    ):
        # Scrub any private keys or sensitive credentials
        safe_params = {
            k: v for k, v in params.items() if "key" not in k.lower() and "secret" not in k.lower()
        }
        event = AuditEvent(
            operation=operation,
            status=status,
            sanitized_parameters=safe_params,
            policy_checks=checks,
            details=details,
        )
        self._audit_log.append(event)

    def _format_description(self, operation: str, params: dict[str, Any]) -> str:
        return format_description(operation, params)
