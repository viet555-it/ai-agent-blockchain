"""Tests for the PolicyEngine (security/policy.py).

Key requirement: "allowlist rỗng = CHẶN TẤT CẢ (deny-by-default)."
"""

from __future__ import annotations

from security.policy import PolicyDecision, PolicyEngine

# ── Test addresses ────────────────────────────────────────────────────

DEMO_ADDR_1 = "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD68"
DEMO_ADDR_2 = "0x267be1C1D684F78cb4F6a176C4911b741E4Ffdc0"
UNKNOWN_ADDR = "0xDeaDbeeF00000000000000000000000000000000"
DEMO_CONTRACT = "0x0000000000000000000000000000000000000000"


def _make_policy(**overrides) -> PolicyEngine:
    """Create a PolicyEngine with customizable config."""
    config = {
        "chain_id": 11155111,
        "allowlist": {
            "addresses": [DEMO_ADDR_1, DEMO_ADDR_2],
            "contracts": [DEMO_CONTRACT],
            "functions": ["deposit", "withdraw"],
        },
        "limits": {
            "per_transaction_eth": "0.1",
            "daily_eth": "0.5",
        },
        "require_simulation": True,
    }
    config.update(overrides)
    return PolicyEngine(config=config)


# ── Deny-by-default tests ────────────────────────────────────────────


class TestDenyByDefault:
    """Core requirement: empty allowlist = BLOCK ALL."""

    def test_empty_address_allowlist_blocks_transfer(self):
        """Empty address allowlist → deny ALL transfers."""
        policy = _make_policy(allowlist={"addresses": [], "contracts": [], "functions": []})
        decision = policy.check_transfer(DEMO_ADDR_1, 0.01)
        assert not decision.allowed
        assert "empty" in decision.reason.lower()

    def test_empty_contract_allowlist_blocks_call(self):
        """Empty contract allowlist → deny ALL contract calls."""
        policy = _make_policy(allowlist={"addresses": [DEMO_ADDR_1], "contracts": [], "functions": ["deposit"]})
        decision = policy.check_contract_call(DEMO_CONTRACT, "deposit")
        assert not decision.allowed
        assert "empty" in decision.reason.lower()

    def test_empty_function_allowlist_blocks_call(self):
        """Empty function allowlist → deny ALL function calls."""
        policy = _make_policy(allowlist={"addresses": [DEMO_ADDR_1], "contracts": [DEMO_CONTRACT], "functions": []})
        decision = policy.check_contract_call(DEMO_CONTRACT, "deposit")
        assert not decision.allowed
        assert "empty" in decision.reason.lower()

    def test_missing_allowlist_key_blocks_all(self):
        """Missing allowlist entirely → deny."""
        policy = PolicyEngine(config={"chain_id": 11155111})
        decision = policy.check_transfer(DEMO_ADDR_1, 0.01)
        assert not decision.allowed


# ── Transfer policy tests ────────────────────────────────────────────


class TestTransferPolicy:
    def test_allowed_address(self):
        policy = _make_policy()
        decision = policy.check_transfer(DEMO_ADDR_1, 0.05)
        assert decision.allowed

    def test_unknown_address_denied(self):
        policy = _make_policy()
        decision = policy.check_transfer(UNKNOWN_ADDR, 0.01)
        assert not decision.allowed
        assert "not in the address allowlist" in decision.reason

    def test_case_insensitive_address(self):
        """Address comparison must be case-insensitive."""
        policy = _make_policy()
        decision = policy.check_transfer(DEMO_ADDR_1.lower(), 0.01)
        assert decision.allowed

    def test_exceeds_per_tx_limit(self):
        policy = _make_policy()
        decision = policy.check_transfer(DEMO_ADDR_1, 0.5)  # limit is 0.1
        assert not decision.allowed
        assert "per-transaction limit" in decision.reason

    def test_exceeds_daily_limit(self):
        policy = _make_policy()
        # Record previous usage close to limit
        policy.record_usage(0.45)
        decision = policy.check_transfer(DEMO_ADDR_1, 0.1)
        assert not decision.allowed
        assert "daily" in decision.reason.lower()

    def test_within_all_limits(self):
        policy = _make_policy()
        decision = policy.check_transfer(DEMO_ADDR_1, 0.05)
        assert decision.allowed


# ── Contract call policy tests ───────────────────────────────────────


class TestContractCallPolicy:
    def test_allowed_contract_and_function(self):
        policy = _make_policy()
        decision = policy.check_contract_call(DEMO_CONTRACT, "deposit")
        assert decision.allowed

    def test_unknown_contract_denied(self):
        policy = _make_policy()
        decision = policy.check_contract_call(UNKNOWN_ADDR, "deposit")
        assert not decision.allowed

    def test_unknown_function_denied(self):
        policy = _make_policy()
        decision = policy.check_contract_call(DEMO_CONTRACT, "selfdestruct")
        assert not decision.allowed
        assert "not in the function allowlist" in decision.reason

    def test_payable_value_limit(self):
        policy = _make_policy()
        decision = policy.check_contract_call(DEMO_CONTRACT, "deposit", value_eth=0.5)
        assert not decision.allowed


# ── Chain ID tests ───────────────────────────────────────────────────


class TestChainId:
    def test_sepolia_matches(self):
        policy = _make_policy()
        decision = policy.check_chain_id(11155111)
        assert decision.allowed

    def test_mainnet_rejected(self):
        policy = _make_policy()
        decision = policy.check_chain_id(1)  # mainnet
        assert not decision.allowed
        assert "Sepolia" in decision.reason


# ── PolicyDecision model tests ───────────────────────────────────────


class TestPolicyDecision:
    def test_allow(self):
        d = PolicyDecision.allow("ok", foo="bar")
        assert d.allowed
        assert d.details == {"foo": "bar"}

    def test_deny(self):
        d = PolicyDecision.deny("blocked", code="DENIED")
        assert not d.allowed
        assert d.details == {"code": "DENIED"}
