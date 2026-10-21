"""Policy Engine – Guardrail for WRITE operations.

Core principle: **deny-by-default**.
- Empty allowlist → BLOCK ALL.
- Every WRITE operation must pass address, contract, function, and value checks.
- Transaction limits enforce per-tx and daily caps.
- Simulation (eth_call) can be required before confirmation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from config.settings import load_policy_config

logger = logging.getLogger(__name__)


@dataclass
class PolicyDecision:
    """Result of a policy check."""

    allowed: bool
    reason: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def allow(cls, reason: str = "Policy check passed", **details: Any) -> PolicyDecision:
        return cls(allowed=True, reason=reason, details=details)

    @classmethod
    def deny(cls, reason: str, **details: Any) -> PolicyDecision:
        return cls(allowed=False, reason=reason, details=details)


class PolicyEngine:
    """Enforces transaction guardrails based on ``config/policy.yaml``.

    Usage::

        engine = PolicyEngine()  # loads policy.yaml
        decision = engine.check_transfer("0xRecipient", 0.05)
        if not decision.allowed:
            raise PermissionError(decision.reason)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config if config is not None else load_policy_config()
        self._allowlist = self._config.get("allowlist", {})
        self._limits = self._config.get("limits", {})
        self._daily_usage: list[tuple[float, float]] = []  # (timestamp, eth_amount)
        logger.info("PolicyEngine loaded: %d addresses, %d contracts, %d functions allowed",
                     len(self.allowed_addresses), len(self.allowed_contracts), len(self.allowed_functions))

    # ── Allowlist accessors ───────────────────────────────────────────

    @property
    def allowed_addresses(self) -> list[str]:
        return [a.lower() for a in self._allowlist.get("addresses", [])]

    @property
    def allowed_contracts(self) -> list[str]:
        return [c.lower() for c in self._allowlist.get("contracts", [])]

    @property
    def allowed_functions(self) -> list[str]:
        return self._allowlist.get("functions", [])

    @property
    def max_per_tx_eth(self) -> float:
        return float(self._limits.get("per_transaction_eth", "0.1"))

    @property
    def max_daily_eth(self) -> float:
        return float(self._limits.get("daily_eth", "0.5"))

    @property
    def require_simulation(self) -> bool:
        return self._config.get("require_simulation", True)

    @property
    def expected_chain_id(self) -> int:
        return self._config.get("chain_id", 11155111)  # Sepolia

    # ── Check methods ─────────────────────────────────────────────────

    def check_transfer(self, to_address: str, value_eth: float) -> PolicyDecision:
        """Check an ETH or ERC-20 transfer against policy.

        Checks:
        1. Allowlist not empty (deny-by-default)
        2. Recipient in address allowlist
        3. Value within per-transaction limit
        4. Value within daily limit
        """
        # 1. Deny-by-default: empty allowlist blocks ALL
        if not self.allowed_addresses:
            return PolicyDecision.deny(
                "Transfer blocked: address allowlist is empty (deny-by-default). "
                "Add addresses to config/policy.yaml → allowlist → addresses."
            )

        # 2. Address check
        if to_address.lower() not in self.allowed_addresses:
            return PolicyDecision.deny(
                f"Recipient {to_address} is not in the address allowlist.",
                address=to_address,
                allowed=self.allowed_addresses,
            )

        # 3. Per-transaction limit
        if value_eth > self.max_per_tx_eth:
            return PolicyDecision.deny(
                f"Transfer of {value_eth} ETH exceeds per-transaction limit of {self.max_per_tx_eth} ETH.",
                value_eth=value_eth,
                limit=self.max_per_tx_eth,
            )

        # 4. Daily limit
        daily_total = self._get_daily_usage() + value_eth
        if daily_total > self.max_daily_eth:
            return PolicyDecision.deny(
                f"Transfer would bring daily total to {daily_total:.4f} ETH, "
                f"exceeding daily limit of {self.max_daily_eth} ETH.",
                daily_total=daily_total,
                limit=self.max_daily_eth,
            )

        return PolicyDecision.allow(
            f"Transfer of {value_eth} ETH to {to_address} is within policy.",
            value_eth=value_eth,
            to=to_address,
        )

    def check_contract_call(
        self, contract_address: str, function_name: str, value_eth: float = 0.0
    ) -> PolicyDecision:
        """Check a contract call against policy.

        Checks:
        1. Contract allowlist not empty (deny-by-default)
        2. Contract in allowlist
        3. Function in allowlist
        4. Value within limits (if payable)
        """
        # 1. Deny-by-default
        if not self.allowed_contracts:
            return PolicyDecision.deny(
                "Contract call blocked: contract allowlist is empty (deny-by-default)."
            )

        # 2. Contract address check
        if contract_address.lower() not in self.allowed_contracts:
            return PolicyDecision.deny(
                f"Contract {contract_address} is not in the contract allowlist.",
                contract=contract_address,
            )

        # 3. Function check
        if not self.allowed_functions:
            return PolicyDecision.deny(
                "Contract call blocked: function allowlist is empty (deny-by-default)."
            )
        if function_name not in self.allowed_functions:
            return PolicyDecision.deny(
                f"Function '{function_name}' is not in the function allowlist. "
                f"Allowed: {self.allowed_functions}",
                function=function_name,
            )

        # 4. Value limit (for payable functions)
        if value_eth > 0:
            if value_eth > self.max_per_tx_eth:
                return PolicyDecision.deny(
                    f"Value {value_eth} ETH exceeds per-transaction limit.",
                    value_eth=value_eth,
                )
            daily_total = self._get_daily_usage() + value_eth
            if daily_total > self.max_daily_eth:
                return PolicyDecision.deny(
                    f"Daily ETH limit would be exceeded ({daily_total:.4f}/{self.max_daily_eth}).",
                )

        return PolicyDecision.allow(
            f"Contract call {function_name}() on {contract_address} is within policy.",
        )

    def check_chain_id(self, chain_id: int) -> PolicyDecision:
        """Verify we are on the expected chain (Sepolia)."""
        if chain_id != self.expected_chain_id:
            return PolicyDecision.deny(
                f"Chain ID mismatch: expected {self.expected_chain_id} (Sepolia), "
                f"got {chain_id}. Refusing to proceed on wrong network.",
                expected=self.expected_chain_id,
                actual=chain_id,
            )
        return PolicyDecision.allow("Chain ID matches Sepolia.")

    # ── Usage tracking ────────────────────────────────────────────────

    def record_usage(self, eth_amount: float) -> None:
        """Record a confirmed transaction for daily limit tracking."""
        self._daily_usage.append((time.time(), eth_amount))

    def _get_daily_usage(self) -> float:
        """Sum of ETH used in the last 24 hours."""
        cutoff = time.time() - 86400
        self._daily_usage = [(t, v) for t, v in self._daily_usage if t > cutoff]
        return sum(v for _, v in self._daily_usage)

    def reset_usage(self) -> None:
        """Reset daily usage tracking (for testing)."""
        self._daily_usage.clear()
