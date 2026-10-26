"""Comprehensive unit & security tests for Guardrail Policy Engine."""
import time
import unittest
from decimal import Decimal
from backend.guardrail.policy_engine import (
    PolicyEngine,
    PolicyConfig,
    GuardrailResult,
    PendingApproval,
)


class GuardrailPolicyEngineTests(unittest.TestCase):
    def setUp(self):
        self.whitelisted_addr = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
        self.non_whitelisted_addr = "0x23618e81E3f5cdF7f54C3d65f7FBc0aBf5B21E8f"
        self.config = PolicyConfig(
            max_native_transfer_limit=Decimal("0.5"),
            max_token_transfer_limit=Decimal("500.0"),
            recipient_whitelist=[self.whitelisted_addr],
            enforce_whitelist=True,
            require_human_approval_for_writes=True,
            approval_timeout_seconds=5,
        )
        self.engine = PolicyEngine(self.config)

    def test_read_operations_allowed_without_approval(self):
        res = self.engine.evaluate_request(
            operation="get_token_balance",
            parameters={"wallet_address": self.whitelisted_addr},
        )
        self.assertTrue(res.is_allowed)
        self.assertFalse(res.requires_approval)
        self.assertEqual(res.operation_type, "READ")
        self.assertEqual(len(res.violations), 0)

    def test_whitelist_allows_authorized_recipient(self):
        res = self.engine.evaluate_request(
            operation="erc20_transfer",
            parameters={
                "recipient": self.whitelisted_addr.lower(),  # test checksum normalization
                "amount": "100.0",
            },
        )
        self.assertTrue(res.is_allowed)
        self.assertTrue(res.requires_approval)
        self.assertEqual(len(res.violations), 0)
        self.assertIsNotNone(res.pending_approval)
        self.assertEqual(res.sanitized_parameters["recipient"], self.whitelisted_addr)

    def test_whitelist_blocks_unauthorized_recipient(self):
        res = self.engine.evaluate_request(
            operation="erc20_transfer",
            parameters={
                "recipient": self.non_whitelisted_addr,
                "amount": "100.0",
            },
        )
        self.assertFalse(res.is_allowed)
        self.assertFalse(res.requires_approval)
        self.assertTrue(any("NOT in the authorized whitelist" in v for v in res.violations))

    def test_native_transfer_amount_limit_enforced(self):
        # Within limit
        res_ok = self.engine.evaluate_request(
            operation="native_transfer",
            parameters={"recipient": self.whitelisted_addr, "amount": "0.4"},
        )
        self.assertTrue(res_ok.is_allowed)

        # Exceeds limit
        res_fail = self.engine.evaluate_request(
            operation="native_transfer",
            parameters={"recipient": self.whitelisted_addr, "amount": "0.6"},
        )
        self.assertFalse(res_fail.is_allowed)
        self.assertTrue(any("exceeds native transfer limit" in v for v in res_fail.violations))

    def test_token_transfer_amount_limit_enforced(self):
        # Exceeds limit 500
        res_fail = self.engine.evaluate_request(
            operation="erc20_transfer",
            parameters={"recipient": self.whitelisted_addr, "amount": "500.01"},
        )
        self.assertFalse(res_fail.is_allowed)
        self.assertTrue(any("exceeds token policy limit" in v for v in res_fail.violations))

    def test_zero_or_negative_amount_blocked(self):
        res_zero = self.engine.evaluate_request(
            operation="erc20_transfer",
            parameters={"recipient": self.whitelisted_addr, "amount": "0"},
        )
        self.assertFalse(res_zero.is_allowed)

        res_neg = self.engine.evaluate_request(
            operation="erc20_transfer",
            parameters={"recipient": self.whitelisted_addr, "amount": "-10"},
        )
        self.assertFalse(res_neg.is_allowed)

    def test_simulation_revert_blocks_request(self):
        sim_data = {"isValid": False, "reason": "AgentToken: Transfer exceeds max limit"}
        res = self.engine.evaluate_request(
            operation="erc20_transfer",
            parameters={"recipient": self.whitelisted_addr, "amount": "100"},
            simulation_data=sim_data,
        )
        self.assertFalse(res.is_allowed)
        self.assertTrue(any("On-chain pre-flight simulation reverted" in v for v in res.violations))

    def test_human_approval_workflow_approve_and_reject(self):
        # 1. Create request
        params = {"recipient": self.whitelisted_addr, "amount": "50.0"}
        res = self.engine.evaluate_request("erc20_transfer", params)
        approval_id = res.pending_approval.approval_id

        # 2. Approve
        ok, msg, pending = self.engine.review_approval(
            approval_id=approval_id,
            action="APPROVE",
            submitted_parameters=params,
            reviewer_comment="Confirmed by user",
        )
        self.assertTrue(ok)
        self.assertEqual(pending.status, "APPROVED")

        # 3. Mark executed
        self.engine.mark_executed(approval_id, tx_hash="0xabc123")
        self.assertEqual(pending.status, "EXECUTED")

        # 4. Cannot re-approve an executed request (anti-replay)
        ok_again, msg_again, _ = self.engine.review_approval(
            approval_id=approval_id,
            action="APPROVE",
            submitted_parameters=params,
        )
        self.assertFalse(ok_again)
        self.assertIn("no longer pending", msg_again)

    def test_tamper_detection_invalidates_approval(self):
        # Attacker tries to tamper with amount or recipient during approval submission!
        original_params = {"recipient": self.whitelisted_addr, "amount": "50.0"}
        res = self.engine.evaluate_request("erc20_transfer", original_params)
        approval_id = res.pending_approval.approval_id

        # Malicious modification: increase amount to 500
        tampered_params = {"recipient": self.whitelisted_addr, "amount": "500.0"}
        ok, msg, pending = self.engine.review_approval(
            approval_id=approval_id,
            action="APPROVE",
            submitted_parameters=tampered_params,
        )
        self.assertFalse(ok)
        self.assertIn("Security Alert", msg)
        self.assertEqual(pending.status, "REJECTED")

    def test_approval_expiration(self):
        # Configure short 1s timeout
        fast_config = PolicyConfig(
            recipient_whitelist=[self.whitelisted_addr],
            approval_timeout_seconds=1,
        )
        engine = PolicyEngine(fast_config)
        params = {"recipient": self.whitelisted_addr, "amount": "10"}
        res = engine.evaluate_request("erc20_transfer", params)
        approval_id = res.pending_approval.approval_id

        time.sleep(1.2)  # Wait for expiration
        ok, msg, pending = engine.review_approval(
            approval_id=approval_id,
            action="APPROVE",
            submitted_parameters=params,
        )
        self.assertFalse(ok)
        self.assertIn("expired", msg)
        self.assertEqual(pending.status, "EXPIRED")

    def test_audit_log_scrubs_private_keys(self):
        params_with_key = {
            "recipient": self.whitelisted_addr,
            "amount": "10",
            "private_key": "0x0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "secret_token": "super_secret_value",
        }
        self.engine.evaluate_request("erc20_transfer", params_with_key)
        events = self.engine.list_audit_events()
        self.assertTrue(len(events) > 0)
        latest = events[0]
        self.assertNotIn("private_key", latest["sanitized_parameters"])
        self.assertNotIn("secret_token", latest["sanitized_parameters"])


if __name__ == "__main__":
    unittest.main()
