"""Fetch explicit candidates with their actual cosine similarity and provenance."""

import math
from collections.abc import Iterable
from typing import Any

from .contracts import RetrievalUnavailable
from .metadata import restore_metadata


def cosine_similarity(distance: float) -> float:
    if not math.isfinite(distance) or not -0.0001 <= distance <= 2.0001:
        raise RetrievalUnavailable("Invalid cosine distance from index")
    return max(-1.0, min(1.0, 1.0 - distance))


def embedding_candidates(
    collection: Any, ids: Iterable[str], vector: list[float], *, direct: bool
) -> dict[str, tuple[str, dict[str, Any], float, bool]]:
    lookup = collection.get(ids=sorted(ids), include=["documents", "metadatas", "embeddings"])
    candidates = {}
    for row_id, text, flat, embedding in zip(
        lookup["ids"], lookup["documents"], lookup["metadatas"], lookup["embeddings"], strict=True
    ):
        denominator = math.sqrt(
            sum(x * x for x in vector) * sum(float(x) * float(x) for x in embedding)
        )
        if denominator <= 0:
            raise RetrievalUnavailable("Zero vector in cosine index")
        similarity = sum(x * float(y) for x, y in zip(vector, embedding, strict=True)) / denominator
        candidates[row_id] = (
            text,
            restore_metadata(row_id, flat),
            cosine_similarity(1.0 - similarity),
            direct,
        )
    return candidates
