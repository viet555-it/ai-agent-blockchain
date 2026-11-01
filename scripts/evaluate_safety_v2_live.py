"""Run a specifically reviewed Gemini safety evaluation, never a blockchain signer."""

import argparse
import json
import os
from pathlib import Path

from config.environment import load_project_env
from eval.safety_v2.live import run_live_evaluation
from eval.safety_v2.live_review import validate_review
from eval.safety_v2.runner import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", required=True)
    parser.add_argument("--approved-review-hash", required=True)
    parser.add_argument("--allow-live-llm", action="store_true")
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--output-root")
    args = parser.parse_args()
    try:
        if not args.allow_live_llm:
            raise ValueError("Explicit --allow-live-llm is required after payload review approval")
        packet = json.loads(Path(args.review).read_text(encoding="utf-8"))
        validate_review(packet)
        if args.approved_review_hash != packet["review_sha256"]:
            raise ValueError("Approval hash does not match reviewed payload")
        load_project_env()
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(ROOT / ".phase3/tiktoken"))
        directory, report = run_live_evaluation(
            packet,
            approved_hash=args.approved_review_hash,
            allow_live=True,
            api_key=os.environ.get("GEMINI_API_KEY", ""),
            case_ids=args.case_ids,
            output_root=args.output_root,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "evidence": str(directory),
                "summaries": report["summaries"],
                "live_provider_requests": report["live_provider_requests"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if any(
        row["status"] in {"error", "not_run"} or row["passed"] is False for row in report["results"]
    ):
        return 1
    return 3 if any(row["status"] == "manual_review" for row in report["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
