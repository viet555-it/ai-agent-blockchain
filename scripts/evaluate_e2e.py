"""G3.5 integrated evaluation: private local EVM, real RAG, zero benchmark broadcast."""

from __future__ import annotations

import argparse
from pathlib import Path

from eval.e2e.cases import not_run as not_run
from eval.e2e.cases import render as render
from eval.e2e.cases import run_case as run_case
from eval.e2e.options import EvaluationOptions, EvaluationUsageError
from eval.e2e.protocol import DATASET as DATASET
from eval.e2e.protocol import LOCK as LOCK
from eval.e2e.protocol import SAFETY as SAFETY
from eval.e2e.protocol import protocol as protocol
from eval.e2e.protocol import sha as sha
from eval.e2e.provider import MeasuredProvider as MeasuredProvider
from eval.e2e.reports import write_report as write_report
from eval.e2e.runner import run_evaluation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["fake", "gemini"], default="fake")
    parser.add_argument("--split", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--safety", action="store_true")
    parser.add_argument(
        "--safety-only",
        action="store_true",
        help="Run only the 20 safety cases, not a benchmark split",
    )
    parser.add_argument("--latency-samples", type=int, default=0)
    parser.add_argument("--request-cap", type=int, default=75)
    parser.add_argument("--allow-live-llm", action="store_true")
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--dev-report", type=Path)
    parser.add_argument(
        "--preview-payload",
        action="store_true",
        help="Record Gemini-format payload locally using FakeLLM only",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    options = EvaluationOptions(**vars(parser.parse_args(argv)))
    try:
        return run_evaluation(options)
    except EvaluationUsageError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
