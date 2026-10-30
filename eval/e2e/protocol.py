"""Runtime fingerprints and exact-protocol gates for freeze and holdout."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from datetime import UTC, datetime
from pathlib import Path

from config.environment import PROJECT_ROOT
from rag.settings import RAGSettings

from .options import EvaluationUsageError

DATASET = PROJECT_ROOT / "eval/e2e_dataset.jsonl"
SAFETY = PROJECT_ROOT / "eval/e2e_safety.jsonl"
LOCK = PROJECT_ROOT / "eval/e2e_lock.json"


def freeze_protocol(dev_report: Path | None, pinned: dict, *, root: Path = PROJECT_ROOT) -> None:
    if not dev_report:
        raise EvaluationUsageError(
            "--freeze requires --dev-report from the current real Gemini dev protocol"
        )
    dev = json.loads(dev_report.read_text(encoding="utf-8"))
    if (
        dev["mode"] != "gemini"
        or dev["split"] != "dev"
        or len(dev["results"]) != 30
        or dev["protocol"] != pinned
        or dev["status"] != "COMPLETED"
    ):
        raise EvaluationUsageError("Dev report is not a full current-protocol Gemini dev run")
    (root / "eval/e2e_lock.json").write_text(
        json.dumps(
            {
                "status": "frozen",
                "frozen_at_utc": datetime.now(UTC).isoformat(),
                "dev_report": str(dev_report.resolve().relative_to(root)),
                "protocol": pinned,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("Frozen current dataset/model/runtime protocol before holdout.")


def require_frozen_protocol(pinned: dict, *, root: Path = PROJECT_ROOT) -> None:
    lock = root / "eval/e2e_lock.json"
    if (
        not lock.exists()
        or json.loads(lock.read_text(encoding="utf-8")).get("status") != "frozen"
        or json.loads(lock.read_text(encoding="utf-8")).get("protocol") != pinned
    ):
        raise EvaluationUsageError("Holdout requires a frozen exact current protocol")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def protocol(model, *, root: Path = PROJECT_ROOT):
    sources = []
    for folder in ["agent", "backend", "tools", "services", "config", "rag"]:
        sources.extend(
            path
            for path in (root / folder).rglob("*.py")
            if "tests" not in path.parts and "__pycache__" not in path.parts
        )
    sources.extend(
        root / name
        for name in [
            "eval/e2e_metrics.py",
            "eval/e2e_runtime.py",
            "eval/e2e_budget.py",
            "scripts/evaluate_e2e.py",
        ]
    )
    sources.extend((root / "eval/e2e").glob("*.py"))
    code = {
        str(path.relative_to(root)).replace("\\", "/"): sha(path) for path in sorted(set(sources))
    }
    index = RAGSettings.load("config/rag.json", root=root).index_dir / "active.json"
    return {
        "dataset_sha256": sha(root / "eval/e2e_dataset.jsonl"),
        "safety_sha256": sha(root / "eval/e2e_safety.jsonl"),
        "source_sha256": code,
        "model": model,
        "temperature": 0,
        "max_steps": 4,
        "max_output_tokens": 512,
        "corpus_manifest_sha256": sha(root / "knowledge/manifest.json"),
        "rag_config_sha256": sha(root / "config/rag.json"),
        "rag_active_sha256": sha(index) if index.exists() else None,
        "fixture_artifact_sha256": sha(
            root / "contracts/artifacts/src/AgentToken.sol/AgentToken.json"
        ),
        "hardhat_config_sha256": sha(root / "contracts/hardhat.config.js"),
        "versions": {
            name: importlib.metadata.version(name)
            for name in [
                "web3",
                "google-genai",
                "fastapi",
                "chromadb",
                "sentence-transformers",
                "pydantic",
            ]
        },
        "chain_id": 31337,
        "benchmark_broadcast_allowed": False,
    }
