"""Rebuild into a temporary index and exercise the documented handoff commands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from eval.run_rag_eval import load_inputs


def main():
    root = Path(__file__).resolve().parents[1]
    lock, _, _ = load_inputs(root)
    runtime = root / "data/rag"
    runtime.mkdir(parents=True, exist_ok=True)
    active = runtime / "active.json"
    original_pointer = active.read_bytes() if active.exists() else None
    stages = []
    with tempfile.TemporaryDirectory(prefix="p8-handoff-", dir=runtime) as directory:
        env = {**os.environ, "PYTHONUTF8": "1", "RAG_INDEX_PATH": directory}

        def command(stage, module, *args, expected_code=0, json_output=True):
            result = subprocess.run([sys.executable, "-m", module, *args], cwd=root, env=env,
                                    capture_output=True, text=True, encoding="utf-8", timeout=180)
            if result.returncode != expected_code:
                raise RuntimeError(f"{stage}: exit {result.returncode}\n{result.stdout}\n{result.stderr}")
            output = json.loads(result.stdout) if json_output else result.stdout
            stages.append(dict(stage=stage, command=[".venv/Scripts/python.exe", "-m", module, *args],
                               exit_code=result.returncode, output=output))
            print(json.dumps(dict(stage=stage, exit_code=result.returncode)), flush=True)
            return output

        built = command("fresh_index", "scripts.ingest_rag", "--verify-git")
        if built["status"] != "built" or built["fingerprint"] != lock["index_fingerprint"]:
            raise RuntimeError("Fresh build differs from frozen corpus/model/chunker")
        if built["chunk_count"] != 159 or built["doc_count"] != 9:
            raise RuntimeError("Unexpected corpus size")
        repeated = command("repeat_ingest", "scripts.ingest_rag", "--verify-git")
        if repeated["status"] != "unchanged" or repeated["collection"] != built["collection"]:
            raise RuntimeError("Repeated ingest did not reuse the generation")
        transfer = command("deployment_query", "scripts.query_rag", "--query", "transfer(address,uint256)", "--k", "3", "--json")
        if transfer["status"] != "ok" or not any(c["metadata"].get("function_signature") == "transfer(address,uint256)" for c in transfer["results"]):
            raise RuntimeError("Transfer interface missing")
        source = command("source_query", "scripts.query_rag", "--scope", "source", "--query", "Theo source faucet có giới hạn bao nhiêu và chờ bao lâu?", "--json")
        if source["status"] != "ok" or not any(c["metadata"]["doc_id"] == "agenttoken-faucet-admin-source" for c in source["results"]):
            raise RuntimeError("Source review evidence missing")
        empty = command("outside_corpus", "scripts.query_rag", "--query", "Cách nấu phở bò ngon", "--json", expected_code=3)
        if empty["status"] != "no_match" or empty["results"] != []:
            raise RuntimeError("Expected no-match")
        text = command("text_cli", "scripts.query_rag", "--query", "transfer(address,uint256)", "--k", "1", json_output=False)
        if "Trạng thái: ok" not in text or "Nguồn:" not in text:
            raise RuntimeError("Text output is incomplete")
        example = command("async_example", "examples.rag_retrieve")
        if not example or any(c["metadata"]["index_fingerprint"] != built["fingerprint"] for c in example):
            raise RuntimeError("Example did not query the rebuilt index")
    if (active.read_bytes() if active.exists() else None) != original_pointer:
        raise RuntimeError("The original active pointer changed")
    report = dict(purpose="P8 fresh-index reproducibility and documented commands, not a fresh dependency installation or new holdout",
                  verified_at_utc=datetime.now(timezone.utc).isoformat(), lock_hash=lock["lock_hash"],
                  index_fingerprint=built["fingerprint"], doc_count=built["doc_count"], chunk_count=built["chunk_count"],
                  original_active_unchanged=True, temporary_index_removed=True, passed=True, stages=stages)
    target = root / "docs/examples/rag_p8_handoff_check.json"
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=True, stages=len(stages), chunk_count=built["chunk_count"])), flush=True)


if __name__ == "__main__":
    main()
