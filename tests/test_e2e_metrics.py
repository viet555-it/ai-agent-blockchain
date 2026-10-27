"""Gold/scoring and the no-broadcast boundary are independent of model outputs."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from web3 import Web3

from eval.e2e_budget import RequestBudget
from eval.e2e_metrics import normalize_argument, percentile, score, summarize, validate_dataset
from eval.e2e_runtime import BenchmarkRPC
from scripts.prepare_e2e_eval import build, build_safety


def response(calls=(), **extra):
    return {
        "error": None,
        "reply": "Results.",
        "requires_approval": False,
        "timeline": [
            {"name": "Tool selected", "tool_name": name, "sanitized_parameters": args}
            for name, args in calls
        ],
        **extra,
    }


class E2EMetricsTests(unittest.TestCase):
    def test_request_budget_survives_restart_and_preserves_phase_caps(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "budget.json"
            budget = RequestBudget(path, {"dev": 2, "safety": 1, "holdout": 1})
            budget.reserve("dev")
            RequestBudget(path, budget.limits).reserve("dev")
            with self.assertRaises(RuntimeError):
                budget.reserve("dev")
            budget.reserve("safety")
            budget.reserve("holdout")
            self.assertEqual(len(budget.snapshot()["reservations"]), 4)
            with self.assertRaises(RuntimeError):
                RequestBudget(path, {"dev": 99}).reserve("dev")

    def setUp(self):
        self.case = {
            "expected": {
                "calls": [{"tool": "get_native_balance", "args": {"address": "0xAbC"}}],
                "supporting_tools": [],
                "action": "read",
                "source_required": False,
                "answer_patterns": [],
            }
        }

    def test_http_or_provider_failures_cannot_score_as_correct_no_tool(self):
        case = {"expected": {"calls": [], "action": "no_tool"}}
        self.assertFalse(score(case, response(), status_code=503)["tools_ok"])
        self.assertFalse(score(case, response(error="LLM_ERROR"))["tools_ok"])

    def test_tool_match_does_not_hide_a_wrong_wallet_parameter(self):
        result = score(self.case, response([("get_native_balance", {"address": "0xDef"})]))
        self.assertTrue(result["tools_ok"])
        self.assertFalse(result["parameters_ok"])
        self.assertFalse(result["success"])

    def test_multi_tool_order_is_free_but_missing_and_extra_tools_fail(self):
        self.case["expected"]["calls"].append(
            {"tool": "get_token_info", "args": {"token_address": "0x123"}}
        )
        rows = [
            ("get_token_info", {"token_address": "0x123"}),
            ("get_native_balance", {"address": "0xabc"}),
        ]
        self.assertTrue(score(self.case, response(rows))["success"])
        self.assertFalse(score(self.case, response(rows[:1]))["tools_ok"])
        self.assertFalse(
            score(self.case, response(rows + [("faucet_claim", {"amount": "10"})]))["tools_ok"]
        )

    def test_exact_decimal_normalization_never_rounds_large_amounts(self):
        self.assertEqual(normalize_argument("amount", "0001.0000"), "1")
        amount = "123456789012345678901234567890.000000000000000001"
        self.assertEqual(normalize_argument("amount", amount), amount)
        self.assertNotEqual(
            normalize_argument("amount", "1.000000000000000001"), normalize_argument("amount", "1")
        )

    def test_optional_arguments_use_real_schema_defaults_without_changing_explicit_values(self):
        case = {
            "expected": {
                "calls": [{"tool": "faucet_claim", "args": {"amount": "100"}}],
                "action": "prepare",
            }
        }
        data = response([("faucet_claim", {})], requires_approval=True)
        self.assertTrue(score(case, data)["parameters_ok"])
        case["expected"]["calls"][0]["args"]["amount"] = "10"
        self.assertFalse(score(case, data)["parameters_ok"])

    def test_faq_requires_real_provider_and_sources(self):
        case = {
            "expected": {
                "calls": [],
                "action": "no_tool",
                "source_required": True,
                "answer_patterns": ["100", "60"],
            }
        }
        data = response(reply="100 AGNT and 60 seconds")
        self.assertFalse(score(case, data)["success"])
        data["rag_result"] = {"provider": "scoped_vector_db", "documents": [{"doc_id": "source"}]}
        self.assertTrue(score(case, data)["success"])

    def test_parameter_denominator_excludes_no_tool_cases_and_failure_remains(self):
        rows = [
            {
                "id": "a",
                "latency_ms": 1,
                "expected": self.case["expected"],
                "score": {"tools_ok": True, "parameters_ok": False, "success": False},
            },
            {
                "id": "b",
                "latency_ms": 100,
                "expected": {"calls": []},
                "score": {"tools_ok": True, "parameters_ok": True, "success": True},
            },
        ]
        summary = summarize(rows)
        self.assertEqual(summary["parameter_cases"], 1)
        self.assertEqual(summary["parameter_accuracy"], 0)
        self.assertEqual(summary["full_success_rate"], 0.5)
        self.assertEqual(percentile(list(range(1, 101)), 95), 95)

    def test_dataset_is_balanced_and_group_leakage_is_rejected(self):
        rows, safety = build(), build_safety()
        validate_dataset(rows, safety)
        changed = copy.deepcopy(rows)
        changed[2]["group"] = changed[0]["group"]
        with self.assertRaisesRegex(ValueError, "leaked"):
            validate_dataset(changed, safety)

    def test_benchmark_guard_blocks_writes_after_web3_middleware_cache(self):
        provider = BenchmarkRPC("http://127.0.0.1:1")
        w3 = Web3(provider)
        with patch.object(
            Web3.HTTPProvider,
            "make_request",
            return_value={"jsonrpc": "2.0", "id": 1, "result": "0x7a69"},
        ) as transport:
            self.assertEqual(w3.eth.chain_id, 31337)
            with self.assertRaises(RuntimeError):
                w3.manager.request_blocking("eth_sendRawTransaction", ["0xdead"])
            transport.assert_called_once()
        self.assertEqual(provider.attempted_writes, 1)
