"""Immutable retrieval scope/options and failure contracts, without model or index imports."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


class InvalidQuery(ValueError):  # noqa: N818 - existing public exception name
    pass


class RetrievalUnavailable(RuntimeError):  # noqa: N818 - existing public exception name
    """Index, encoder or stored data is unavailable; this is not a no-match."""


class RetrievalTimeout(TimeoutError):  # noqa: N818 - existing public exception name
    pass


@dataclass(frozen=True)
class SourceScope:
    """Explicit review of source documentation; never a deployment capability claim."""

    doc_version: str
    include_general: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.doc_version, str) or not self.doc_version.strip():
            raise ValueError("Source doc_version is required")
        if type(self.include_general) is not bool:
            raise ValueError("include_general must be boolean")

    def accepts(self, metadata: dict[str, Any]) -> bool:
        if metadata.get("scope") == "general":
            return self.include_general
        return (
            metadata.get("scope") == "source_only"
            and metadata.get("doc_version") == self.doc_version
        )


@dataclass(frozen=True)
class RetrievalOptions:
    min_similarity: float = 0.45
    candidate_pool: int = 32
    context_max_tokens: int = 1024
    max_query_chars: int = 2000
    timeout_seconds: float = 15.0
    max_concurrency: int = 1
    max_per_parent: int = 2
    parent_context: bool = False
    general_categories: tuple[str, ...] = ("web3",)

    def __post_init__(self) -> None:
        if type(self.parent_context) is not bool:
            raise ValueError("parent_context must be boolean")
        if (
            type(self.min_similarity) not in (int, float)
            or not math.isfinite(self.min_similarity)
            or not -1 <= self.min_similarity <= 1
        ):
            raise ValueError("min_similarity must be finite and between -1 and 1")
        for name, lower, upper in (
            ("candidate_pool", 10, 100),
            ("context_max_tokens", 1, 16384),
            ("max_query_chars", 1, 10000),
            ("max_concurrency", 1, 8),
            ("max_per_parent", 1, 10),
        ):
            value = getattr(self, name)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be an integer in {lower}..{upper}")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be positive and finite")
        if not isinstance(self.general_categories, tuple) or any(
            not isinstance(c, str) or not c for c in self.general_categories
        ):
            raise ValueError("general_categories must be a tuple of category names")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> RetrievalOptions:
        if not isinstance(value, dict):
            raise ValueError("retrieval config must be an object")
        value = dict(value)
        if "general_categories" in value:
            if not isinstance(value["general_categories"], (list, tuple)):
                raise ValueError("general_categories must be an array")
            value["general_categories"] = tuple(value["general_categories"])
        return cls(**value)
