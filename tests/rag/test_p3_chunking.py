import copy
import unittest
from pathlib import Path

from rag.chunking import ChunkingError, TokenBudget, _split_body, chunk_documents
from rag.loaders import SourceDocument, content_hash, load_corpus
from rag.models import DeploymentScope

ROOT = Path(__file__).resolve().parents[2]


def budget(limit=900):
    return TokenBudget(lambda text: len(text.encode("utf-8")), limit, "test-utf8", unit="utf8_bytes")


def document(text):
    return SourceDocument(text, "markdown", dict(
        doc_id="demo", title="Demo", scope="general", doc_version="v1",
        verification_status="source_reviewed", content_hash=content_hash(text),
        source_path="demo.md", source_origin="workspace", source_commit=None,
    ))


class ChunkingTest(unittest.TestCase):
    def test_real_corpus_is_deterministic_and_preserves_source_scope(self):
        docs = load_corpus("knowledge/manifest.json", root=ROOT)
        first = chunk_documents(docs, budget=budget(2048))
        second = chunk_documents(docs, budget=budget(2048))
        self.assertEqual(first, second)
        self.assertEqual(len({c.metadata["chunk_id"] for c in first}), len(first))
        by_doc = {d.metadata["doc_id"]: d.metadata for d in docs}
        for chunk in first:
            source = by_doc[chunk.metadata["doc_id"]]
            for key, value in source.items():
                self.assertEqual(chunk.metadata[key], value)
            self.assertEqual(chunk.metadata["chunk_hash"], content_hash(chunk.content))
            self.assertLessEqual(len(chunk.content.encode("utf-8")), 2048)
            self.assertNotIn("score", chunk.to_dict())

    def test_abi_functions_are_separate_and_keep_signatures(self):
        docs = [d for d in load_corpus("knowledge/manifest.json", root=ROOT) if d.source_format == "abi_json"]
        chunks = chunk_documents(docs, budget=budget(2048))
        functions = [c for c in chunks if c.metadata["abi_entry_type"] == "function"]
        self.assertEqual(len(functions), 23)
        self.assertEqual(len({c.metadata["parent_id"] for c in functions}), 23)
        self.assertIn("transferFrom(address,address,uint256)", {c.metadata["function_signature"] for c in functions})
        self.assertTrue(all(c.metadata["function_signature"] in c.content for c in functions))

    def test_long_sections_preserve_exact_body_and_protected_values(self):
        address = "0x" + "a" * 40
        amount = "1.000000000000000001"
        body = (f"Chuyển `{amount}` tới `{address}` bằng `transfer(address,uint256)`.\n\n" * 12)
        prefix = "Source\n"
        fragments = _split_body(body, prefix, budget(240))
        self.assertGreater(len(fragments), 1)
        self.assertEqual("".join(fragments), body)
        for value in (address, amount, "transfer(address,uint256)"):
            self.assertEqual(sum(part.count(value) for part in fragments), body.count(value))
        self.assertTrue(all(len((prefix + part).encode("utf-8")) <= 240 for part in fragments))

    def test_continuation_chunks_keep_function_and_parent(self):
        doc = document("# Token\n\n## transfer(address,uint256)\n\n" + "Kiểm tra số dư. " * 100)
        chunks = chunk_documents([doc], budget=budget(300))
        self.assertGreater(len(chunks), 1)
        self.assertEqual(len({c.metadata["parent_id"] for c in chunks}), 1)
        self.assertEqual([c.metadata["part_index"] for c in chunks], list(range(len(chunks))))
        self.assertTrue(all(c.metadata["function_signature"] == "transfer(address,uint256)" for c in chunks))
        self.assertTrue(all(c.metadata["part_count"] == len(chunks) for c in chunks))

    def test_code_fences_do_not_create_fake_headings_or_split(self):
        code = "```python\n# not a heading\n\nprint('xin chào')\n```\n"
        doc = document("# Token\n\n## Ví dụ\n\n" + code + "\nGiải thích.\n")
        chunks = chunk_documents([doc], budget=budget(900))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["heading_path"], "Token > Ví dụ")
        self.assertIn(code, chunks[0].content)
        # A code block with blank lines must stay atomic even on the splitting path.
        body = ("Đoạn đầu. " * 50) + "\n\n" + code + ("Đoạn sau. " * 50)
        fragments = _split_body(body, "Source\n", budget(220))
        self.assertEqual("".join(fragments), body)
        self.assertEqual(sum(code in part for part in fragments), 1)

    def test_oversized_atoms_and_bad_fences_fail_without_truncation(self):
        for text in ("# Test\n\n`" + "x" * 500 + "`", "# Test\n\n```\nunclosed", "# Title only\n"):
            with self.subTest(text=text[:30]), self.assertRaises(ChunkingError):
                chunk_documents([document(text)], budget=budget(250))
        with self.assertRaisesRegex(ChunkingError, "prefix"):
            chunk_documents([document("# Title\n\nbody")], budget=budget(5))

    def test_counter_includes_model_special_tokens_and_no_implicit_estimate(self):
        counter = lambda text: len(text) + 2  # Test double for an encoder adding two special tokens.
        encoding_budget = TokenBudget(counter, 200, "test-encoder-with-specials")
        chunks = chunk_documents([document("# Test\n\n" + "hello " * 100)], budget=encoding_budget)
        for chunk in chunks:
            self.assertEqual(chunk.metadata["token_count"], counter(chunk.content))
            self.assertLessEqual(counter(chunk.content), 200)
        for invalid in (lambda _: True, lambda _: -1, lambda _: 1.5):
            with self.assertRaises(ChunkingError):
                chunk_documents([document("# Test\n\nbody")], budget=TokenBudget(invalid, 100, "bad"))

    def test_changed_content_or_budget_changes_ids_without_mutating_documents(self):
        doc = document("# Test\n\nBody")
        original = copy.deepcopy(doc.metadata)
        first = chunk_documents([doc], budget=budget())
        changed = chunk_documents([document("# Test\n\nChanged body")], budget=budget())
        other_budget = chunk_documents([doc], budget=budget(1000))
        self.assertNotEqual(first[0].metadata["chunk_id"], changed[0].metadata["chunk_id"])
        self.assertNotEqual(first[0].metadata["chunk_id"], other_budget[0].metadata["chunk_id"])
        self.assertEqual(doc.metadata, original)

    def test_scope_filter_still_rejects_source_only_after_chunking(self):
        import json
        manifest = json.loads((ROOT / "knowledge/manifest.json").read_text(encoding="utf-8"))
        scope = DeploymentScope(**manifest["deployment_scope"])
        chunks = chunk_documents(load_corpus("knowledge/manifest.json", root=ROOT), budget=budget(2048))
        source_only = [c for c in chunks if c.metadata["scope"] == "source_only"]
        self.assertTrue(source_only)
        self.assertTrue(all(not scope.accepts(c.metadata) for c in source_only))


if __name__ == "__main__":
    unittest.main()
