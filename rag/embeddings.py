"""Pinned, local CPU embeddings with strict preflight token and vector checks."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from rag.chunking import TokenBudget


class EmbeddingError(ValueError):
    pass


class SentenceEmbeddingProvider:
    def __init__(
        self, *, model_id: str, revision: str, cache_dir: str | Path,
        batch_size: int = 16, threads: int = 2, offline: bool = True,
    ) -> None:
        if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise EmbeddingError("Model revision must be a full pinned Hugging Face commit")
        if not model_id or type(batch_size) is not int or batch_size < 1:
            raise EmbeddingError("Valid model_id and positive batch_size required")
        if type(threads) is not int or threads < 1:
            raise EmbeddingError("threads must be a positive integer")
        # Heavy dependencies are optional until P4 is explicitly used.
        import torch
        from huggingface_hub import snapshot_download

        torch.set_num_threads(threads)
        snapshot = snapshot_download(
            repo_id=model_id, revision=revision, cache_dir=str(cache_dir),
            local_files_only=offline,
            allow_patterns=["*.json", "model.safetensors", "sentencepiece.bpe.model", "tokenizer.model"],
            token=False,
        )
        if not (Path(snapshot) / "modules.json").is_file():
            raise EmbeddingError("Snapshot has no SentenceTransformer modules.json")
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(
            snapshot, device="cpu", local_files_only=True, trust_remote_code=False,
            model_kwargs={"use_safetensors": True},
        )
        if self.model.default_prompt_name:
            raise EmbeddingError("A model with a default prompt needs an explicit token-budget adapter")
        self.model_id = model_id
        self.revision = revision
        self.batch_size = batch_size
        self.max_tokens = int(self.model.max_seq_length)
        self.dimension = int(self.model.get_embedding_dimension())
        if self.max_tokens < 1 or self.dimension < 1:
            raise EmbeddingError("Invalid encoder limits")
        self.tokenizer_id = f"{model_id}@{revision}"
        self.budget = TokenBudget(self.count_tokens, self.max_tokens, self.tokenizer_id)
        self.snapshot_path = str(snapshot)

    def count_tokens(self, text: str) -> int:
        return len(self.model.tokenizer.encode(text, add_special_tokens=True, truncation=False, verbose=False))

    @property
    def identity(self) -> dict[str, Any]:
        return dict(
            provider="sentence-transformers", model_id=self.model_id, revision=self.revision,
            dimension=self.dimension, max_tokens=self.max_tokens, normalize_embeddings=True,
            device="cpu", dtype="float32", prompt="",
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        for text in texts:
            if not isinstance(text, str) or not text.strip():
                raise EmbeddingError("Embedding input must be non-empty text")
            count = self.count_tokens(text)
            if count > self.max_tokens:
                raise EmbeddingError(f"Input has {count} tokens; encoder limit is {self.max_tokens}. Re-chunk instead of truncating.")
        if not texts:
            return []
        vectors = self.model.encode(
            texts, batch_size=self.batch_size, prompt="", normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False, device="cpu",
        ).tolist()
        if len(vectors) != len(texts):
            raise EmbeddingError("Encoder returned the wrong vector count")
        for vector in vectors:
            if len(vector) != self.dimension or not all(math.isfinite(x) for x in vector):
                raise EmbeddingError("Encoder returned invalid vectors")
            norm = math.sqrt(sum(x * x for x in vector))
            if abs(norm - 1.0) > 0.001:
                raise EmbeddingError("Encoder returned a zero or non-normalized vector")
        return vectors
