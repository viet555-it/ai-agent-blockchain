"""Evaluation options and validation, independent of argparse and runtime resources."""

from dataclasses import dataclass, replace
from pathlib import Path


class EvaluationUsageError(ValueError):
    """An invalid evaluation request; the CLI maps this to argparse's usage error."""


@dataclass(frozen=True)
class EvaluationOptions:
    mode: str = "fake"
    split: str = "dev"
    safety: bool = False
    safety_only: bool = False
    latency_samples: int = 0
    request_cap: int = 75
    allow_live_llm: bool = False
    freeze: bool = False
    dev_report: Path | None = None
    preview_payload: bool = False


def validate_options(options: EvaluationOptions) -> EvaluationOptions:
    if options.safety_only:
        options = replace(options, safety=True)
        if options.latency_samples:
            raise EvaluationUsageError("Safety-only does not run the latency workload")
    if not 1 <= options.request_cap <= 150 or options.latency_samples not in {0, 100}:
        raise EvaluationUsageError("request cap must be 1..150; latency samples must be 0 or 100")
    if options.latency_samples and options.mode != "fake":
        raise EvaluationUsageError("The 100-request infrastructure latency run must use fake LLM")
    if options.preview_payload and options.mode != "fake":
        raise EvaluationUsageError("Payload preview must use fake mode; it never calls Google")
    if options.mode == "gemini" and options.safety and not options.safety_only:
        raise EvaluationUsageError(
            "Run Gemini safety separately with --safety-only to enforce its approved 50-request allocation"
        )
    return options
