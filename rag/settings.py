"""Explicit RAG-only configuration; independent of backend/agent settings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from rag.loaders import parse_json


@dataclass(frozen=True)
class RAGSettings:
    model_id: str
    revision: str
    cache_dir: Path
    index_dir: Path
    batch_size: int
    threads: int
    prefix_style: str

    @classmethod
    def load(cls, path: str | Path, *, root: Path) -> "RAGSettings":
        path = Path(path)
        if not path.is_absolute():
            path = root / path
        value = parse_json(path.read_text(encoding="utf-8"), str(path))
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise ValueError("Expected RAG config schema_version 1")
        if not isinstance(value.get("model_id"), str) or not value["model_id"].strip():
            raise ValueError("model_id is required")
        if not isinstance(value.get("revision"), str) or not re.fullmatch(r"[0-9a-f]{40}", value["revision"]):
            raise ValueError("revision must be a pinned model commit")
        for key in ("batch_size", "threads"):
            if type(value.get(key)) is not int or value[key] < 1:
                raise ValueError(f"{key} must be positive")
        if value.get("prefix_style") not in {"verbose", "compact"}:
            raise ValueError("Invalid prefix_style")

        def location(key: str, env_name: str) -> Path:
            raw = os.environ.get(env_name, value.get(key))
            if not isinstance(raw, str) or not raw.strip():
                raise ValueError(f"{key} is required")
            target = Path(raw)
            return (target if target.is_absolute() else root / target).resolve()

        return cls(
            value["model_id"], value["revision"], location("cache_dir", "RAG_CACHE_PATH"),
            location("index_dir", "RAG_INDEX_PATH"), value["batch_size"], value["threads"], value["prefix_style"],
        )
