"""Run a reviewed followup using the original shared budget and per-case limits."""

import argparse
import json
import os
from pathlib import Path

from config.environment import load_project_env
from eval.safety_v2.continuation import ContinuationLedger
from eval.safety_v2.live import run_live_evaluation
from eval.safety_v2.live_review import validate_review
from eval.safety_v2.runner import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent-review", required=True)
    parser.add_argument("--review", required=True)
    parser.add_argument("--approved-review-hash", required=True)
    parser.add_argument("--allow-live-llm", action="store_true")
    args = parser.parse_args()
    try:
        if not args.allow_live_llm:
            raise ValueError("Followup needs explicit live execution authorization")
        packet = json.loads(Path(args.review).read_text(encoding="utf-8"))
        parent = json.loads(Path(args.parent_review).read_text(encoding="utf-8"))
        validate_review(packet)
        if args.approved_review_hash != packet["review_sha256"]:
            raise ValueError("Followup approval hash mismatch")
        load_project_env()
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ValueError("GEMINI_API_KEY is required")
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(ROOT / ".phase3/tiktoken"))
        ledger = ContinuationLedger(ROOT / ".phase3/safety-v2-live-budget.json", parent, packet)
        directory, report = run_live_evaluation(
            packet,
            approved_hash=args.approved_review_hash,
            allow_live=True,
            api_key=key,
            request_ledger=ledger,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "evidence": str(directory),
                "summaries": report["summaries"],
                "new_requests": report["live_provider_requests"],
                "original_grant_used": len(report["request_reservations"]["reservations"]),
                "original_grant_cap": report["request_reservations"]["limits"]["total_requests"],
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
