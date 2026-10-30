"""CLI validation and exact-protocol gates without starting runtime or a provider."""

import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from eval.e2e.options import EvaluationOptions, EvaluationUsageError, validate_options
from eval.e2e.protocol import freeze_protocol, protocol, require_frozen_protocol
from eval.e2e.runner import run_evaluation
from scripts.evaluate_e2e import main


class EvaluationProtocolTests(unittest.TestCase):
    def test_invalid_cli_options_exit_before_environment_or_runtime_access(self):
        for arguments in (
            ["--request-cap", "151"],
            ["--latency-samples", "1"],
            ["--safety-only", "--latency-samples", "100"],
            ["--mode", "gemini", "--latency-samples", "100"],
            ["--mode", "gemini", "--preview-payload"],
            ["--mode", "gemini", "--safety"],
        ):
            with (
                self.subTest(arguments=arguments),
                contextlib.redirect_stderr(io.StringIO()),
                patch("eval.e2e.runner.dotenv_values") as environment,
                self.assertRaises(SystemExit) as caught,
            ):
                main(arguments)
            self.assertEqual(caught.exception.code, 2)
            environment.assert_not_called()

    def test_safety_only_normalization_keeps_callers_options_immutable(self):
        original = EvaluationOptions(safety_only=True)
        normalized = validate_options(original)
        self.assertTrue(normalized.safety)
        self.assertFalse(original.safety)
        self.assertEqual(normalized, replace(original, safety=True))

    def test_live_mode_requires_flag_and_complete_configuration_before_session_start(self):
        configured = {
            "LLM_PROVIDER": "gemini",
            "LLM_MODEL": "test-model",
            "GEMINI_API_KEY": "test-key",
        }
        for allow_live, changes in (
            (False, {}),
            (True, {"LLM_PROVIDER": "fake"}),
            (True, {"LLM_MODEL": ""}),
            (True, {"GEMINI_API_KEY": ""}),
        ):
            with (
                self.subTest(allow_live=allow_live, changes=changes),
                patch("eval.e2e.runner.dotenv_values", return_value=dict(configured, **changes)),
                patch("eval.e2e.runner.protocol", return_value={}),
                patch("eval.e2e.runner.evaluate_session") as execute,
                self.assertRaises(EvaluationUsageError),
            ):
                run_evaluation(EvaluationOptions(mode="gemini", allow_live_llm=allow_live))
            execute.assert_not_called()

    def test_freeze_requires_full_current_real_dev_and_preserves_lock_on_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "eval").mkdir()
            path = root / "eval/dev.json"
            lock = root / "eval/e2e_lock.json"
            lock.write_text("historical lock", encoding="utf-8")
            pinned = {"model": "test-model", "source_sha256": {"runner.py": "abc"}}
            valid = dict(
                mode="gemini", split="dev", results=[{}] * 30, protocol=pinned, status="COMPLETED"
            )
            for changes in (
                {"mode": "fake"},
                {"split": "holdout"},
                {"results": [{}] * 29},
                {"protocol": {"model": "other"}},
                {"status": "LIMIT_REACHED"},
            ):
                with self.subTest(changes=changes):
                    path.write_text(json.dumps(dict(valid, **changes)), encoding="utf-8")
                    with self.assertRaises(EvaluationUsageError):
                        freeze_protocol(path, pinned, root=root)
                    self.assertEqual(lock.read_text(encoding="utf-8"), "historical lock")
            path.write_text(json.dumps(valid), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                freeze_protocol(path, pinned, root=root)
            require_frozen_protocol(pinned, root=root)
            with self.assertRaises(EvaluationUsageError):
                require_frozen_protocol({"model": "changed"}, root=root)

    def test_protocol_hashes_include_all_extracted_modules_and_detect_changes(self):
        source_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [
                "eval/e2e_dataset.jsonl",
                "eval/e2e_safety.jsonl",
                "eval/e2e_metrics.py",
                "eval/e2e_runtime.py",
                "eval/e2e_budget.py",
                "scripts/evaluate_e2e.py",
                "knowledge/manifest.json",
                "config/rag.json",
                "contracts/hardhat.config.js",
                "contracts/artifacts/src/AgentToken.sol/AgentToken.json",
                *[
                    path.relative_to(source_root).as_posix()
                    for path in (source_root / "eval/e2e").glob("*.py")
                ],
            ]
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            with (
                patch(
                    "eval.e2e.protocol.RAGSettings.load",
                    return_value=SimpleNamespace(index_dir=root / "index"),
                ),
                patch("eval.e2e.protocol.importlib.metadata.version", return_value="test-version"),
            ):
                pinned = protocol("test-model", root=root)
                modules = {name for name in names if name.startswith("eval/e2e/")}
                self.assertTrue(modules.issubset(pinned["source_sha256"]))
                (root / "eval/e2e_lock.json").write_text(
                    json.dumps(dict(status="frozen", protocol=pinned)), encoding="utf-8"
                )
                for name in sorted(modules):
                    with self.subTest(module=name):
                        path = root / name
                        path.write_text("changed", encoding="utf-8")
                        changed = protocol("test-model", root=root)
                        with self.assertRaises(EvaluationUsageError):
                            require_frozen_protocol(changed, root=root)
                        path.write_text("fixture", encoding="utf-8")
