"""Run safety v2 locally with real policy/ledger code and optional scripted FakeLLM."""

import argparse
import json
import os

from eval.safety_v2.runner import ROOT, run_evaluation


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["both", "policy", "fake_agent"], default="both")
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--output-root")
    args = parser.parse_args()
    os.environ.setdefault("TIKTOKEN_CACHE_DIR", str(ROOT / ".phase3/tiktoken"))
    try:
        directory, report = run_evaluation(
            mode=args.mode, case_ids=args.case_ids, output_root=args.output_root
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {"evidence": str(directory), "summaries": report["summaries"]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return (
        1 if any(r["status"] == "error" or r["passed"] is False for r in report["results"]) else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
