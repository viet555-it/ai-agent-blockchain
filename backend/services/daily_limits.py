"""Durable rolling-24h amount limits, independent of wallet auth and policy configuration.

All amounts are base units. Trusted workflow callers supply scope/limits and own
transactions, so reservation can share the authorize/send-lock commit in a later step.
This service does not grant signing permission or replace other guardrail checks.
"""

import math
import re
from dataclasses import dataclass

from backend.db.repositories import daily_limits as repository
from backend.token_amounts import UINT256_MAX

WINDOW_SECONDS = 86400


def amount_units(value, *, positive=False):
    if type(value) not in (int, str) or not re.fullmatch(r"[0-9]{1,78}", str(value)):
        raise ValueError("Expected a uint256 integer or decimal integer string in base units")
    number = int(value)
    if number > UINT256_MAX or (positive and number == 0):
        raise ValueError("Amount is outside the permitted uint256 range")
    return number


def timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("Expected a finite non-negative UTC timestamp")
    return value


@dataclass(frozen=True)
class LimitScope:
    wallet_id: str
    deployment_id: str
    asset_id: str

    def values(self):
        for value in (self.wallet_id, self.deployment_id):
            if not isinstance(value, str) or not value.strip() or len(value) > 36:
                raise ValueError("Invalid wallet/deployment identity")
        if not isinstance(self.asset_id, str) or not re.fullmatch(
            r"native|erc20:0x[0-9a-f]{40}", self.asset_id
        ):
            raise ValueError("Asset must be native or a canonical lowercase ERC20 address")
        return {
            "wallet_id": self.wallet_id,
            "deployment_id": self.deployment_id,
            "asset_id": self.asset_id,
        }


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    reason_code: str
    spent: int
    reserved: int
    remaining: int


class DailyLimitService:
    @staticmethod
    def evaluate(connection, scope, amount, *, per_tx_limit, daily_limit, now):
        scope_values = scope.values()
        amount = amount_units(amount, positive=True)
        per_tx, daily = amount_units(per_tx_limit), amount_units(daily_limit)
        if per_tx > daily:
            raise ValueError("Per-transaction limit must not exceed daily limit")
        spent, reserved = repository.usage(connection, scope_values, timestamp(now), WINDOW_SECONDS)
        remaining = max(0, daily - spent - reserved)
        reason = (
            "PER_TX_LIMIT_EXCEEDED"
            if amount > per_tx
            else ("DAILY_LIMIT_EXCEEDED" if amount > remaining else "POLICY_OK")
        )
        return LimitDecision(reason == "POLICY_OK", reason, spent, reserved, remaining)

    def reserve(self, connection, scope, reservation_id, amount, *, per_tx_limit, daily_limit, now):
        self._id(reservation_id)
        values = scope.values()
        amount = amount_units(amount, positive=True)
        timestamp(now)
        repository.lock_scope(connection, values)
        prior = repository.find(connection, reservation_id)
        if prior:
            if (
                any(prior[key] != value for key, value in values.items())
                or int(prior["amount_base_units"]) != amount
                or prior["status"] != "RESERVED"
            ):
                raise ValueError("Reservation ID reused with different data or terminal state")
            # An idempotent retry returns the existing reservation, not permission to sign again.
            snapshot = self.evaluate(
                connection,
                scope,
                amount,
                per_tx_limit=per_tx_limit,
                daily_limit=daily_limit,
                now=now,
            )
            return LimitDecision(
                True, "ALREADY_RESERVED", snapshot.spent, snapshot.reserved, snapshot.remaining
            )
        decision = self.evaluate(
            connection, scope, amount, per_tx_limit=per_tx_limit, daily_limit=daily_limit, now=now
        )
        if decision.allowed:
            repository.reserve(connection, values, reservation_id, amount, now)
        return decision

    def settle_success(self, connection, reservation_id, *, block_timestamp, now):
        spent_at = timestamp(block_timestamp)
        if spent_at > timestamp(now):
            raise ValueError("Verified block timestamp cannot be in the future")
        self._settle(connection, reservation_id, "SPENT", spent_at)

    def release_reverted(self, connection, reservation_id):
        """Call only after verifying a reverted receipt; client rejection is insufficient."""
        self._settle(connection, reservation_id, "REVERTED")

    def _settle(self, connection, reservation_id, status, spent_at=None):
        self._id(reservation_id)
        repository.lock_entry(connection, reservation_id)
        prior = repository.find(connection, reservation_id)
        if not prior:
            raise ValueError("Unknown reservation")
        if prior["status"] == status and prior["spent_at"] == spent_at:
            return
        if prior["status"] != "RESERVED":
            raise ValueError("Conflicting terminal reservation outcome")
        repository.settle(connection, reservation_id, status, spent_at)

    @staticmethod
    def _id(reservation_id):
        if (
            not isinstance(reservation_id, str)
            or not reservation_id.strip()
            or len(reservation_id) > 128
        ):
            raise ValueError("Invalid reservation ID")
