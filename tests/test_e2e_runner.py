"""Evaluation failure and quota outcomes retain cases, evidence and the send boundary."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from eval.e2e.options import EvaluationOptions, validate_options
from eval.e2e.provider import MeasuredProvider
from eval.e2e.reports import write_report
from eval.e2e.runner import evaluate_session


def case(name):
    return dict(
        id=name,
        split="dev",
        category="read",
        language="en",
        prompt="Read {{wallet}}",
        expected={"calls": [{"tool": "get_native_balance", "args": {"address": "{{wallet}}"}}]},
    )


def result(name, *, error=None, attempted=0):
    success = error is None and attempted == 0
    return dict(
        case(name),
        phase="benchmark",
        latency_ms=1.0,
        stage_ms=dict.fromkeys(["rag", "llm", "rpc", "policy", "prepare"], 0.1),
        error=error,
        attempted_writes=attempted,
        generation_requests=1,
        score=dict(success=success, tools_ok=success, parameters_ok=success),
    )


class EvaluationRunnerTests(unittest.TestCase):
    def run_fixture(self, root, options, *, outcome=None, startup_error=None, safety=()):
        rows = [case(name) for name in ("A", "B", "C")]
        runtime = MagicMock()
        runtime.bindings = {"wallet": "0x" + "11" * 20}
        runtime.nonce = 1
        runtime.rpc.attempted_writes = 0
        runtime.rpc.methods = {}
        runtime.w3.eth.get_transaction_count.return_value = 1
        runtime.startup_ms = runtime.app_cold_start_ms = 1.0
        manager = MagicMock()
        manager.__enter__.return_value = runtime
        manager.__enter__.side_effect = startup_error
        inner = Mock(last_error={"http_status": 429}, call_count=1, total_usage={})
        budget = Mock()
        budget.snapshot.return_value = {"limits": {}, "reservations": []}
        evidence = root / "evidence"
        with (
            patch("eval.e2e.runner.EvaluationRuntime", return_value=manager),
            patch("eval.e2e.runner.GeminiProvider", return_value=inner),
            patch("eval.e2e.runner.RequestBudget", return_value=budget),
            patch("eval.e2e.runner.logging.disable"),
            patch(
                "eval.e2e.runner.subprocess.run", return_value=SimpleNamespace(stdout="test-sha\n")
            ),
            patch("eval.e2e.runner.run_case", side_effect=outcome) as execute,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = evaluate_session(
                options,
                rows,
                list(safety),
                {},
                "test-model",
                "test-key",
                root=root,
                evidence_dir=evidence,
            )
        report = json.loads((evidence / "results.json").read_text(encoding="utf-8"))
        self.assertEqual(
            len((evidence / "samples.csv").read_text(encoding="utf-8").splitlines()),
            len(report["results"]) + len(report["safety_results"]) + 1,
        )
        return code, report, execute, manager

    def test_quota_failure_stops_calls_and_keeps_remaining_cases_in_denominator(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report, execute, manager = self.run_fixture(
                Path(directory),
                EvaluationOptions(mode="gemini"),
                outcome=[result("A", error="LLM_ERROR")],
            )
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "LIMIT_REACHED")
        self.assertEqual(report["summary"]["n"], 3)
        self.assertEqual(report["not_run_cases"], 2)
        self.assertEqual(report["safety_results"], [])
        self.assertEqual([row["id"] for row in report["results"]], ["A", "B", "C"])
        execute.assert_called_once()
        manager.__exit__.assert_called_once()

    def test_startup_failure_still_writes_complete_not_run_json_and_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report, execute, _ = self.run_fixture(
                Path(directory), EvaluationOptions(), startup_error=RuntimeError("startup failed")
            )
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "INFRASTRUCTURE_FAILURE")
        self.assertEqual(report["failure_type"], "RuntimeError")
        self.assertEqual(report["not_run_cases"], 3)
        self.assertEqual(report["summary"]["failures"], ["A", "B", "C"])
        execute.assert_not_called()

    def test_forbidden_broadcast_attempt_stops_before_another_case(self):
        with tempfile.TemporaryDirectory() as directory:
            code, report, execute, manager = self.run_fixture(
                Path(directory), EvaluationOptions(), outcome=[result("A", attempted=1)]
            )
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "INFRASTRUCTURE_FAILURE")
        self.assertEqual(report["not_run_cases"], 2)
        self.assertEqual(report["results"][0]["attempted_writes"], 1)
        execute.assert_called_once()
        manager.__exit__.assert_called_once()

    def test_safety_only_runs_no_benchmark_or_latency_workload(self):
        safety = [case("S1"), case("S2")]
        options = validate_options(EvaluationOptions(safety_only=True))
        with tempfile.TemporaryDirectory() as directory:
            code, report, execute, _ = self.run_fixture(
                Path(directory), options, outcome=[result("S1"), result("S2")], safety=safety
            )
        self.assertEqual(code, 0)
        self.assertEqual(report["results"], [])
        self.assertEqual(report["latency_samples"], [])
        self.assertEqual(len(report["safety_results"]), 2)
        self.assertTrue(all(call.kwargs["safety"] for call in execute.call_args_list))

    def test_failed_atomic_replacement_keeps_previous_report_and_retries_six_times(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = {"status": "RUNNING", "results": ["first"]}
            write_report(root, original)
            with (
                patch.object(Path, "replace", side_effect=PermissionError("busy")) as replace,
                patch("eval.e2e.reports.time.sleep") as sleep,
                self.assertRaises(PermissionError),
            ):
                write_report(root, {"status": "COMPLETED"})
            self.assertEqual(
                json.loads((root / "results.json").read_text(encoding="utf-8")), original
            )
            self.assertEqual(replace.call_count, 6)
            self.assertEqual(sleep.call_count, 5)


class MeasuredProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_reservation_failure_prevents_provider_call_and_records_timing(self):
        inner = SimpleNamespace(call_count=0, _max_calls=1, chat=AsyncMock())
        provider = MeasuredProvider(inner)
        provider.live_budget = Mock()
        provider.live_budget.reserve.side_effect = RuntimeError("budget reached")
        provider.budget_phase = "dev"
        with self.assertRaisesRegex(RuntimeError, "budget reached"):
            await provider.chat(messages=[])
        inner.chat.assert_not_awaited()
        provider.live_budget.reserve.assert_called_once_with("dev")
        self.assertEqual(len(provider.timings), 1)
