"""Validate P1 provenance and deployment isolation, offline with stdlib only."""

import hashlib
import json
import subprocess
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from rag.models import DeploymentScope

ROOT = Path(__file__).resolve().parents[2]


def text_hash(text):
    return "sha256:" + hashlib.sha256(text.replace("\r\n", "\n").encode()).hexdigest()


class P1ContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "knowledge/manifest.json").read_text(encoding="utf-8"))
        cls.chunk = json.loads((ROOT / "tests/rag/fixtures/chunk.json").read_text(encoding="utf-8"))
        cls.scope = DeploymentScope(**cls.manifest["deployment_scope"])

    def test_sources_are_pinned_and_match_workspace(self):
        paths = []
        doc_ids = []

        def check_reference(source):
            path = source["source_path"]
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn("..", Path(path).parts)
            origin = source.get("source_origin", "git")
            if origin == "git":
                self.assertRegex(source["source_commit"], r"^[0-9a-f]{40}$")
                committed = subprocess.check_output(
                    ["git", "show", f"{source['source_commit']}:{path}"], cwd=ROOT
                ).decode("utf-8")
                self.assertEqual(text_hash(committed), source["content_hash"])
            else:
                self.assertEqual(origin, "workspace")
                self.assertIsNone(source["source_commit"])
                self.assertEqual(
                    text_hash((ROOT / path).read_text(encoding="utf-8")),
                    source["content_hash"],
                )

        for source in self.manifest["sources"]:
            with self.subTest(source=source["doc_id"]):
                path = source["source_path"]
                check_reference(source)
                self.assertEqual(text_hash((ROOT / path).read_text(encoding="utf-8")), source["content_hash"])
                for reference in source.get("derived_from", []):
                    check_reference(reference)
                paths.append(path)
                doc_ids.append(source["doc_id"])
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(len(doc_ids), len(set(doc_ids)))

    def test_deployment_scope_matches_manifest_and_abi(self):
        deployment = json.loads((ROOT / "backend/abi/11155111/deployment.json").read_text())
        self.assertEqual(self.scope.chain_id, int(deployment["chainId"]))
        self.assertEqual(self.scope.contract_address, deployment["contractAddress"])
        abi = next(s for s in self.manifest["sources"] if s["doc_id"] == "agenttoken-sepolia-abi")
        self.assertEqual(self.scope.abi_hash, abi["content_hash"])
        self.assertEqual(abi["verification_status"], "repository_only")

    def test_chunk_fixture_matches_agent_shape_and_source(self):
        self.assertEqual(set(self.chunk), {"content", "metadata", "score"})
        self.assertIsInstance(self.chunk["content"], str)
        self.assertIsInstance(self.chunk["score"], float)
        meta = self.chunk["metadata"]
        source = next(s for s in self.manifest["sources"] if s["doc_id"] == meta["doc_id"])
        for key in ("source_path", "source_commit", "content_hash", "doc_version", "abi_hash"):
            self.assertEqual(meta[key], source[key])
        abi = json.loads((ROOT / source["source_path"]).read_text())
        self.assertIn(json.loads(self.chunk["content"]), abi)
        self.assertTrue(self.scope.accepts(meta))

    def test_scope_rejects_other_chain_address_version_and_source_only(self):
        for change in (
            {"chain_id": 1}, {"chain_id": "11155111"},
            {"contract_address": "0x" + "1" * 40},
            {"doc_version": "other-version"}, {"abi_hash": "sha256:" + "0" * 64},
            {"scope": "source_only"}, {"scope": "policy_snapshot"}, {"scope": "unknown"},
        ):
            with self.subTest(change=change):
                self.assertFalse(self.scope.accepts({**self.chunk["metadata"], **change}))
        self.assertFalse(self.scope.accepts({}))
        self.assertTrue(self.scope.accepts({"scope": "general"}))
        self.assertFalse(replace(self.scope, include_general=False).accepts({"scope": "general"}))

    def test_scope_is_immutable_and_validated(self):
        with self.assertRaises(FrozenInstanceError):
            self.scope.chain_id = 1
        for change in (
            {"chain_id": True}, {"chain_id": 0}, {"contract_address": "0x" + "0" * 40},
            {"contract_address": "invalid"}, {"abi_hash": "invalid"},
            {"doc_version": " "}, {"include_general": "yes"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.scope, **change)


if __name__ == "__main__":
    unittest.main()
