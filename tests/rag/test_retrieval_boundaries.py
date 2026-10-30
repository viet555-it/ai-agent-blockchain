"""Provenance and dependency boundaries after splitting retrieval helpers."""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from eval.run_rag_eval import load_inputs
from rag.index import fingerprint
from rag.loaders import content_hash
from rag.retrieval import contracts
from rag.retrieval.metadata import restore_metadata

ROOT = Path(__file__).resolve().parents[2]


class RetrievalBoundaryTests(unittest.TestCase):
    def test_contracts_import_without_loading_runtime_model_or_index(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from rag.retrieval.contracts import SourceScope, RetrievalOptions; "
                "assert not {'rag.retriever', 'rag.index', 'rag.embeddings', "
                "'chromadb', 'sentence_transformers'} & sys.modules.keys()",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_old_imports_share_canonical_contract_objects(self):
        from rag import retriever
        from rag.retrieval.signatures import explicit_signatures

        for name in (
            "InvalidQuery",
            "RetrievalOptions",
            "RetrievalTimeout",
            "RetrievalUnavailable",
            "SourceScope",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(retriever, name), getattr(contracts, name))
        self.assertIs(retriever.explicit_signatures, explicit_signatures)

    def test_restored_provenance_rejects_identity_usage_and_scalar_type_spoofing(self):
        fixture = json.loads((ROOT / "tests/rag/fixtures/chunk.json").read_text(encoding="utf-8"))
        metadata = dict(
            fixture["metadata"],
            usage="ingest",
            source_origin="git",
            chunk_hash=content_hash(fixture["content"]),
            parent_id="section",
        )
        flat = {
            key: value for key, value in metadata.items() if type(value) in (str, int, float, bool)
        }
        flat["record_json"] = json.dumps(metadata)
        self.assertEqual(restore_metadata(metadata["chunk_id"], flat), metadata)
        mutations = (
            ("row-id", metadata["chunk_id"] + "-different", flat),
            ("scalar-type", metadata["chunk_id"], dict(flat, chain_id=float(metadata["chain_id"]))),
            ("usage", metadata["chunk_id"], dict(flat, usage="reference_only")),
            ("source-commit", metadata["chunk_id"], dict(flat, source_commit="b" * 40)),
        )
        for name, row_id, stored in mutations:
            with self.subTest(name=name), self.assertRaises(contracts.RetrievalUnavailable):
                restore_metadata(row_id, stored)
        missing_provenance = copy.deepcopy(metadata)
        missing_provenance.pop("source_commit")
        with self.assertRaises(contracts.RetrievalUnavailable):
            restore_metadata(
                metadata["chunk_id"], dict(flat, record_json=json.dumps(missing_provenance))
            )

    def test_config_conversion_does_not_retain_mutable_category_input(self):
        categories = ["web3"]
        config = {"general_categories": categories, "max_per_parent": 5}
        options = contracts.RetrievalOptions.from_dict(config)
        self.assertIs(config["general_categories"], categories)
        categories.append("policy")
        self.assertEqual(options.general_categories, ("web3",))


class RetrievalFreezeTests(unittest.TestCase):
    def test_extracted_runtime_modules_are_frozen_and_mutations_are_rejected(self):
        lock, _, _ = load_inputs(ROOT)
        modules = {
            path.relative_to(ROOT).as_posix() for path in (ROOT / "rag/retrieval").glob("*.py")
        }
        self.assertTrue(modules.issubset(lock["runtime_hashes"]))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            names = set(lock["runtime_hashes"]) | {
                "eval/rag_eval_lock.json",
                "eval/rag_dataset.jsonl",
                "eval/rag_gold_catalog.json",
                "config/rag.json",
            }
            for name in names:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            for name in sorted(modules):
                with self.subTest(module=name):
                    path = target / name
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n# mutation\n")
                    with self.assertRaisesRegex(ValueError, "Frozen runtime changed"):
                        load_inputs(target)
                    path.write_bytes(original)

    def test_previous_lock_and_reports_remain_identifiable(self):
        lock, _, _ = load_inputs(ROOT)
        revision = lock["structure_revision"]
        previous = json.loads((ROOT / revision["previous_lock"]).read_text(encoding="utf-8"))
        self.assertEqual(previous["lock_hash"], revision["previous_lock_hash"])
        self.assertEqual(
            fingerprint({key: value for key, value in previous.items() if key != "lock_hash"}),
            previous["lock_hash"],
        )
        for name in (
            "dataset_hash",
            "gold_catalog_hash",
            "config_hash",
            "index_fingerprint",
            "embedding",
        ):
            self.assertEqual(lock[name], previous[name])
        for split in ("dev", "holdout"):
            report = json.loads(
                (ROOT / f"eval/rag_results_{split}.json").read_text(encoding="utf-8")
            )
            self.assertIn(report["lock_hash"], (previous["lock_hash"], lock["lock_hash"]))
        self.assertEqual(
            content_hash((ROOT / revision["equivalence_report"]).read_text(encoding="utf-8")),
            revision["equivalence_report_hash"],
        )
