"""Explicit initial model download; resolve a commit once and save local RAG config."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import time
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    config_path = root / "config/rag.json"
    model_id = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    from huggingface_hub import HfApi
    from rag.embeddings import SentenceEmbeddingProvider

    started = time.perf_counter()
    api = HfApi(token=False)
    if config_path.is_file():
        value = json.loads(config_path.read_text(encoding="utf-8"))
        model_id, revision = value["model_id"], value["revision"]
    else:
        info = api.model_info(model_id)
        revision = info.sha
        value = dict(schema_version=1, model_id=model_id, revision=revision,
                     cache_dir=".cache/rag/huggingface", index_dir="data/rag",
                     batch_size=16, threads=2, prefix_style="compact")
    print(json.dumps({"model_id": model_id, "pinned_revision": revision}), flush=True)
    provider = SentenceEmbeddingProvider(
        model_id=model_id, revision=revision, cache_dir=root / value["cache_dir"],
        batch_size=value["batch_size"], threads=value["threads"], offline=False,
    )
    vectors = provider.embed(["Chuyển token an toàn", "Faucet cấp token thử nghiệm"])
    info = api.model_info(model_id, revision=revision)
    card = info.card_data.to_dict() if info.card_data else {}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    import psutil
    snapshot_bytes = sum(p.stat().st_size for p in Path(provider.snapshot_path).rglob("*") if p.is_file())
    report = dict(
        embedding=provider.identity, initial_smoke_vector_count=len(vectors),
        license=card.get("license"), model_snapshot_bytes=snapshot_bytes,
        setup_elapsed_seconds=round(time.perf_counter() - started, 3),
        process_rss_bytes=psutil.Process().memory_info().rss,
        machine_ram_bytes=psutil.virtual_memory().total,
        python=platform.python_version(), platform=platform.platform(),
        packages={p: importlib.metadata.version(p) for p in
                  ("torch", "sentence-transformers", "transformers", "chromadb", "huggingface-hub", "numpy")},
    )
    report_path = root / "docs/examples/rag_p4_model_smoke.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
