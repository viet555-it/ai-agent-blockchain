"""Shared transaction errors and proposal records."""

from dataclasses import dataclass
from typing import Any

from backend.guardrail.policy_engine import GuardrailResult

SUPPORTED = {"native_transfer", "erc20_transfer", "faucet_claim"}


class TransactionError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class BoundProposal:
    operation: str
    parameters: dict[str, Any]
    transaction: dict[str, Any]
    session_id: str
    parameter_hash: str
    result: dict[str, Any] | None = None


@dataclass
class PreparedProposal:
    decision: GuardrailResult
    transaction: dict[str, Any] | None = None
