"""Wallet failures shared by workflows, workers and API adapters."""

from enum import StrEnum
from typing import NoReturn


class WalletErrorKind(StrEnum):
    INVALID_INPUT = "invalid_input"
    AUTHENTICATION_REQUIRED = "authentication_required"
    PERMISSION_DENIED = "permission_denied"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"


class WalletError(Exception):
    def __init__(self, kind: WalletErrorKind, code: str, message: str):
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.message = message


def fail(kind: WalletErrorKind, code: str, message: str) -> NoReturn:
    raise WalletError(kind, code, message)
