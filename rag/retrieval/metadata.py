"""Restore stored provenance and validate scalar filter metadata."""

from __future__ import annotations

import re
from typing import Any

from rag.loaders import parse_json

from .contracts import RetrievalUnavailable


def stored_signatures(metadata: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    if metadata.get("function_signature"):
        result.add(metadata["function_signature"])
    if metadata.get("function_signatures_json"):
        items = parse_json(metadata["function_signatures_json"], "stored function signatures")
        if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
            raise RetrievalUnavailable("Invalid stored signature list")
        result.update(items)
    return result


def restore_metadata(row_id: str, flat: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(flat, dict) or not isinstance(flat.get("record_json"), str):
        raise RetrievalUnavailable("Stored chunk has no provenance record")
    metadata = parse_json(flat["record_json"], "record_json")
    required = (
        "chunk_id",
        "doc_id",
        "title",
        "category",
        "source_path",
        "content_hash",
        "scope",
        "doc_version",
        "verification_status",
        "chunk_hash",
        "parent_id",
    )
    if not isinstance(metadata, dict) or any(
        not isinstance(metadata.get(key), str) or not metadata[key] for key in required
    ):
        raise RetrievalUnavailable("Stored chunk has incomplete metadata")
    if metadata["chunk_id"] != row_id or metadata.get("usage") != "ingest":
        raise RetrievalUnavailable("Stored chunk identity/usage is invalid")
    origin, commit = metadata.get("source_origin"), metadata.get("source_commit")
    if "source_commit" not in metadata or origin not in {"git", "workspace"}:
        raise RetrievalUnavailable("Stored chunk is missing source provenance")
    if origin == "git" and (
        not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)
    ):
        raise RetrievalUnavailable("Stored Git source_commit is invalid")
    if origin == "workspace" and commit is not None:
        raise RetrievalUnavailable("Stored workspace source_commit must be null")
    for key, value in metadata.items():
        if type(value) in (str, int, float, bool) and (
            key not in flat or type(flat[key]) is not type(value) or flat[key] != value
        ):
            raise RetrievalUnavailable("Stored filter metadata differs from provenance record")
    return metadata
