"""Metric and frozen-dataset checks; quality itself uses the real model runner."""

import json
import tempfile
import unittest
from pathlib import Path

from eval.run_rag_eval import load_inputs, make_scope, percentile, score_case, summarize
from rag.retriever import RetrievalOptions, SourceScope


ROOT = Path(__file__).resolve().parents[2]


class EvaluationTest(unittest.TestCase):
    def test_recall_counts_all_gold_chunks_not_only_document_hits(self):
        case = dict(id="x", category="source", query="test", mode="source", expect_empty=False,
                    gold_chunk_ids=["a", "b"], gold_doc_ids=["doc"])
        chunks = [dict(content="part", score=.5, metadata=dict(chunk_id="a", doc_id="doc", scope="source_only", doc_version="v1"))]
        row = score_case(case, chunks, SourceScope("v1"), RetrievalOptions())
        self.assertEqual(row["recall_at_5"], .5)
        self.assertTrue(row["doc_hit_at_5"])
        self.assertEqual(summarize([row])["recall_at_5"], .5)

    def test_empty_results_and_errors_have_different_no_match_outcomes(self):
        case = dict(id="n", category="outside", query="test", mode="source", expect_empty=True,
                    gold_chunk_ids=[], gold_doc_ids=[])
        ok = score_case(case, [], SourceScope("v1"), RetrievalOptions())
        failed = score_case(case, [], SourceScope("v1"), RetrievalOptions(), error="missing index")
        self.assertIsNone(ok["recall_at_5"])
        self.assertTrue(ok["no_match_correct"])
        self.assertFalse(failed["no_match_correct"])
        self.assertEqual(summarize([ok, failed])["errors"], 1)

    def test_scope_and_general_category_leaks_are_counted(self):
        case = dict(id="x", category="scope", query="test", mode="source", expect_empty=True,
                    gold_chunk_ids=[], gold_doc_ids=[])
        chunks = [dict(score=.5, metadata=dict(chunk_id="a", doc_id="doc", scope="source_only", doc_version="v2")),
                  dict(score=.5, metadata=dict(chunk_id="b", doc_id="policy", scope="general", category="policy"))]
        row = score_case(case, chunks, SourceScope("v1"), RetrievalOptions())
        self.assertEqual(row["scope_leak_ids"], ["a", "b"])
        self.assertEqual(summarize([row])["scope_leak_chunks"], 2)

    def test_percentiles_use_nearest_rank_not_max_or_mean(self):
        self.assertEqual(percentile(list(range(1, 101)), .5), 50)
        self.assertEqual(percentile(list(range(1, 101)), .95), 95)
        with self.assertRaises(ValueError):
            percentile([], .95)

    def test_frozen_dataset_is_balanced_and_gold_matches_scope(self):
        lock, cases, gold = load_inputs(ROOT)
        self.assertEqual(len(cases), 40)
        self.assertEqual(lock["benchmark_queries"], 100)
        manifest = json.loads((ROOT / "knowledge/manifest.json").read_text(encoding="utf-8"))
        for case in cases:
            scope = make_scope(case, manifest)
            for chunk_id in case["gold_chunk_ids"]:
                self.assertTrue(scope.accepts(gold[chunk_id]["metadata"]))
                self.assertTrue(gold[chunk_id]["content"])

    def test_changed_config_is_rejected_before_model_initialization(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp)
            for name in ["eval/rag_eval_lock.json", "eval/rag_dataset.jsonl", "eval/rag_gold_catalog.json", "config/rag.json", "rag/retriever.py", "eval/run_rag_eval.py"]:
                path = target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            config = target / "config/rag.json"
            config.write_text(config.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Frozen input changed"):
                load_inputs(target)


if __name__ == "__main__":
    unittest.main()
