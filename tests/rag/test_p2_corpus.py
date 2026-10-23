"""Check corpus/ABI consistency and provenance boundaries without RPC or models."""

import json
import re
import unittest
from pathlib import Path

from rag.models import DeploymentScope

ROOT = Path(__file__).resolve().parents[2]


def signature(entry):
    return entry.get("name", "constructor") + "(" + ",".join(
        param["type"] for param in entry["inputs"]
    ) + ")"


def parameters(items):
    return ", ".join(
        item["type"] + " " + (item.get("name") or "(không đặt tên)")
        for item in items
    ) or "(không có)"


class P2CorpusTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "knowledge/manifest.json").read_text(encoding="utf-8"))
        cls.abi = json.loads((ROOT / "backend/abi/11155111/AgentToken_abi.json").read_text())

    def test_documentation_covers_actual_abi_inputs_outputs_and_mutability(self):
        text = (ROOT / "knowledge/contracts/agenttoken-abi.md").read_text(encoding="utf-8")
        sections = dict(re.findall(r"^## ([^\n]+)\n(.*?)(?=^## |\Z)", text, re.M | re.S))
        actual_functions = {
            signature(entry): entry for entry in self.abi
            if entry["type"] in ("function", "constructor")
        }
        documented_functions = {heading for heading in sections if heading.endswith(")")}
        self.assertEqual(documented_functions, set(actual_functions))
        for sig, entry in actual_functions.items():
            with self.subTest(signature=sig):
                section = sections[sig]
                self.assertIn("- Input: `" + parameters(entry["inputs"]) + "`.", section)
                self.assertIn("- Output: `" + parameters(entry.get("outputs", [])) + "`.", section)
                self.assertIn("- Mutability: `" + entry["stateMutability"] + "`.", section)

    def test_event_and_error_catalogue_matches_abi(self):
        text = (ROOT / "knowledge/contracts/agenttoken-abi.md").read_text(encoding="utf-8")
        events = text.split("## Events trong ABI\n", 1)[1].split("## Custom errors", 1)[0]
        errors = text.split("## Custom errors trong ABI\n", 1)[1].split("## Ghi chú", 1)[0]
        for kind, section in (("event", events), ("error", errors)):
            documented = set(re.findall(r"^- `([^`]+)`", section, re.M))
            expected = {signature(entry) for entry in self.abi if entry["type"] == kind}
            self.assertEqual(documented, expected)

    def test_markdown_allowlist_and_authoring_provenance(self):
        sources = [s for s in self.manifest["sources"] if s["source_format"] == "markdown"]
        found = {path.relative_to(ROOT).as_posix() for path in (ROOT / "knowledge").rglob("*.md")}
        self.assertEqual(found, {s["source_path"] for s in sources})
        for source in sources:
            with self.subTest(source=source["doc_id"]):
                text = (ROOT / source["source_path"]).read_text(encoding="utf-8")
                self.assertIn("Doc-ID: " + source["doc_id"] + ".", text)
                self.assertIn("Scope: " + source["scope"] + ".", text)
                self.assertEqual(source["source_origin"], "workspace")
                self.assertIsNone(source["source_commit"])
                self.assertTrue(source["derived_from"])
                for reference in source["external_references"]:
                    self.assertTrue(reference["url"].startswith("https://"))
                    self.assertRegex(reference["checked_at"], r"^\d{4}-\d{2}-\d{2}$")

    def test_deployment_retrieval_does_not_accept_source_or_policy_explanations(self):
        scope = DeploymentScope(**self.manifest["deployment_scope"])
        for source in self.manifest["sources"]:
            with self.subTest(source=source["doc_id"]):
                accepted = scope.accepts(source)
                expected = source["scope"] in ("general", "deployed_contract")
                self.assertEqual(accepted, expected)
                if source["scope"] == "policy_snapshot":
                    self.assertEqual(source["usage"], "reference_only")
                    self.assertTrue(source["policy_version"])
        ingest_paths = {s["source_path"] for s in self.manifest["sources"] if s["usage"] == "ingest"}
        self.assertNotIn("contracts/README.md", ingest_paths)
        self.assertFalse(any("contracts/exported/" in path for path in ingest_paths))


if __name__ == "__main__":
    unittest.main()
