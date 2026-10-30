"""Guardrail contracts; the mutable engine is loaded when requested."""

from backend.guardrail.models import AuditEvent, GuardrailResult, PendingApproval, PolicyConfig
from backend.guardrail.rules import READ_OPERATIONS, WRITE_OPERATIONS

__all__ = [
    "PolicyEngine",
    "PolicyConfig",
    "AuditEvent",
    "PendingApproval",
    "GuardrailResult",
    "READ_OPERATIONS",
    "WRITE_OPERATIONS",
]


def __getattr__(name):
    if name == "PolicyEngine":
        from backend.guardrail.policy_engine import PolicyEngine

        return PolicyEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
