"""Meaningful source validation regressions using an isolated temporary corpus."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rag.loaders import SourceError, abi_signature, content_hash, load_corpus, validate_abi

ROOT = Path(__file__).resolve().parents[2]


class LoaderTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.scope = dict(chain_id=11155111, contract_address="0x" + "1" * 40,
                          abi_hash="sha256:" + "a" * 64, doc_version="v1")
        self.manifest = dict(schema_version=2, deployment_scope=self.scope, sources=[])
        (self.root / "evidence.txt").write_text("Evidence\n", encoding="utf-8")
        self.evidence = dict(source_origin="workspace", source_path="evidence.txt",
                             source_commit=None, content_hash=content_hash("Evidence\n"))

    def source(self, text="# Hướng dẫn\n\nChuyển 5 token.\n", path="doc.md", fmt="markdown", **extra):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))
        source = dict(doc_id="doc", source_path=path, source_origin="workspace",
                      source_commit=None, content_hash=content_hash(text), title="Tài liệu",
                      category="web3", source_format=fmt, scope="general", doc_version="v1",
                      verification_status="source_reviewed", usage="ingest",
                      derived_from=[copy.deepcopy(self.evidence)])
        source.update(extra)
        self.manifest["sources"].append(source)
        return source

    def load(self):
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        return load_corpus(path, root=self.root)

    def test_unicode_crlf_and_unlisted_files(self):
        self.source("# Số dư\r\n\r\nVí 0x123: 1.000000000000000001 token.\r\n")
        (self.root / "not-approved.json").write_text("not JSON", encoding="utf-8")
        docs = self.load()
        self.assertEqual(len(docs), 1)
        self.assertIn("Số dư", docs[0].text)
        self.assertNotIn("\r", docs[0].text)
        self.assertEqual(docs[0].metadata["content_hash"], content_hash(docs[0].text))

    def test_stale_content_and_workspace_evidence_fail(self):
        source = self.source()
        original = (self.root / "doc.md").read_bytes()
        (self.root / "doc.md").write_text("Changed", encoding="utf-8")
        with self.assertRaisesRegex(SourceError, "hash mismatch"):
            self.load()
        (self.root / "doc.md").write_bytes(original)
        (self.root / "evidence.txt").write_text("Changed evidence", encoding="utf-8")
        with self.assertRaisesRegex(SourceError, "evidence hash mismatch"):
            self.load()
        self.assertIsNone(source["source_commit"])

    def test_reference_only_not_read_or_returned(self):
        source = self.source()
        source.update(usage="reference_only", source_format="solidity_reference")
        (self.root / "doc.md").unlink()
        self.assertEqual(self.load(), [])

    def test_duplicate_id_path_and_content_rejected(self):
        self.source()
        baseline = copy.deepcopy(self.manifest)
        for changes in ({"doc_id": "doc"}, {"source_path": "doc.md"}, {}):
            with self.subTest(changes=changes):
                self.manifest = copy.deepcopy(baseline)
                self.source(doc_id="other", path="other.md")
                self.manifest["sources"][-1].update(changes)
                with self.assertRaisesRegex(SourceError, "Duplicate"):
                    self.load()

    def test_path_escape_and_noncanonical_paths_rejected(self):
        source = self.source()
        for path in ("../secret.md", "/secret.md", "C:/secret.md", "dir\\secret.md", "./doc.md", "a/../doc.md"):
            with self.subTest(path=path):
                source["source_path"] = path
                with self.assertRaises(SourceError):
                    self.load()

    def test_empty_bad_json_and_wrong_extensions_rejected(self):
        for text, path, fmt in (
            (" \n", "doc.md", "markdown"),
            ("{", "abi.json", "abi_json"),
            ("[]", "abi.json", "abi_json"),
            ('{"x":1,"x":2}', "abi.json", "abi_json"),
            ("NaN", "abi.json", "abi_json"),
            ("text", "secret.env", "markdown"),
        ):
            with self.subTest(text=text, path=path):
                self.manifest["sources"] = []
                self.source(text=text, path=path, fmt=fmt)
                with self.assertRaises(SourceError):
                    self.load()

    def test_manifest_schema_and_provenance_are_required(self):
        self.source()
        baseline = copy.deepcopy(self.manifest)
        for changes in (
            {"source_origin": "unknown"}, {"source_commit": "a" * 40},
            {"source_origin": "git", "source_commit": "short"},
            {"derived_from": []}, {"scope": "all"}, {"content_hash": "invalid"},
        ):
            with self.subTest(changes=changes):
                self.manifest = copy.deepcopy(baseline)
                self.manifest["sources"][0].update(changes)
                with self.assertRaises(SourceError):
                    self.load()
        self.manifest = copy.deepcopy(baseline)
        self.manifest["schema_version"] = 1
        with self.assertRaisesRegex(SourceError, "schema_version"):
            self.load()

    def test_deployment_content_and_metadata_must_match_scope(self):
        body = dict(chainId="11155111", contractAddress=self.scope["contract_address"])
        self.source(text=json.dumps(body), path="deployment.json", fmt="deployment_json",
                    scope="deployed_contract", **{k: v for k, v in self.scope.items() if k != "doc_version"})
        self.assertEqual(len(self.load()), 1)
        self.manifest["sources"][0]["chain_id"] = 1
        with self.assertRaisesRegex(SourceError, "metadata"):
            self.load()
        self.manifest["sources"][0]["chain_id"] = 11155111
        body["contractAddress"] = "0x" + "2" * 40
        text = json.dumps(body)
        (self.root / "deployment.json").write_text(text, encoding="utf-8")
        self.manifest["sources"][0]["content_hash"] = content_hash(text)
        with self.assertRaisesRegex(SourceError, "content does not match"):
            self.load()

    def test_real_corpus_git_evidence_and_reference_exclusion(self):
        docs = load_corpus("knowledge/manifest.json", root=ROOT, verify_git=True)
        self.assertEqual(len(docs), 9)
        self.assertTrue(all(d.metadata["usage"] == "ingest" for d in docs))
        self.assertNotIn("policy_snapshot", {d.metadata["scope"] for d in docs})

    def test_optional_git_verification_reports_errors(self):
        docs = load_corpus("knowledge/manifest.json", root=ROOT)
        self.assertTrue(docs)
        with patch("rag.loaders.subprocess.check_output", return_value=b"wrong content"):
            with self.assertRaisesRegex(SourceError, "Git evidence hash mismatch"):
                load_corpus("knowledge/manifest.json", root=ROOT, verify_git=True)

    def test_abi_overloads_and_tuple_array_signatures(self):
        entry = dict(type="function", name="set", stateMutability="nonpayable", outputs=[],
                     inputs=[dict(type="tuple[]", components=[dict(type="address"), dict(type="uint256")])])
        self.assertEqual(abi_signature(entry), "set((address,uint256)[])")
        overload = {**entry, "inputs": [dict(type="uint256")]
                    }
        self.assertEqual(len(validate_abi([entry, overload])), 2)
        with self.assertRaisesRegex(SourceError, "Duplicate ABI"):
            validate_abi([entry, copy.deepcopy(entry)])
        for changes in ({"inputs": "bad"}, {"outputs": None}, {"stateMutability": "wrong"},
                        {"inputs": [dict(type="uint37")]}, {"inputs": [dict(type="tuple")]},
                        {"inputs": [dict(type="uint256[0]")]}, {"name": ""}):
            with self.subTest(changes=changes), self.assertRaises(SourceError):
                validate_abi([{**entry, **changes}])


if __name__ == "__main__":
    unittest.main()
