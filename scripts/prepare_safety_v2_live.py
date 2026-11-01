"""Prepare a local payload review for a new Gemini evaluation; never calls its API."""

import argparse
import json
from pathlib import Path

from eval.safety_v2.live_review import build_review, write_review
from eval.safety_v2.runner import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--request-cap", type=int, default=80)
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--continue-review", help="Original reviewed packet, preserved as evidence")
    parser.add_argument("--output", default=str(ROOT / "eval/safety_v2/live-review"))
    args = parser.parse_args()
    try:
        parent = (
            json.loads(Path(args.continue_review).read_text(encoding="utf-8"))
            if args.continue_review
            else None
        )
        packet = build_review(
            args.model,
            request_cap=args.request_cap,
            case_ids=args.case_ids,
            continuation_of=parent["review_sha256"] if parent else None,
        )
        write_review(Path(args.output), packet)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "output": args.output,
                "review_sha256": packet["review_sha256"],
                "cases": len(packet["review"]["cases"]),
                "limits": packet["review"]["limits"],
                "provider_requests": 0,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
