import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from rag.retriever import InvalidQuery, RetrievalTimeout, RetrievalUnavailable, SourceScope
from scripts.query_rag import main, parser, prepare


CHUNK = dict(content="Số dư và đơn vị token", score=0.75, metadata=dict(
    title="Đơn vị token", source_path="knowledge/web3/token-units.md", source_commit=None,
    scope="general", doc_version="v1", verification_status="source_reviewed", chunk_id="demo:1",
    selection_reason="semantic",
))


class FakeRetriever:
    def __init__(self, *, results=None, error=None):
        self.results = [CHUNK] if results is None else results
        self.error = error
        self.closed = False

    async def retrieve(self, query, k=5):
        if self.error:
            raise self.error
        return self.results[:k]

    async def aclose(self):
        self.closed = True


class QueryCLITest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "config").mkdir()
        (self.root / "knowledge").mkdir()
        self.manifest = dict(schema_version=2, deployment_scope=dict(
            chain_id=11155111, contract_address="0x" + "a" * 40,
            abi_hash="sha256:" + "a" * 64, doc_version="repo-v1", include_general=True,
        ), sources=[dict(scope="source_only", usage="ingest", doc_version="source-v1")])
        self.write_manifest()
        (self.root / "config/rag.json").write_text(json.dumps(dict(retrieval={})), encoding="utf-8")
        self.created = []

    def write_manifest(self):
        (self.root / "knowledge/manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def invoke(self, arguments, *, retriever=None, factory_error=None):
        stub = retriever or FakeRetriever()

        async def factory(**kwargs):
            self.created.append(kwargs)
            if factory_error:
                raise factory_error
            return stub

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["--root", str(self.root), *arguments], factory=factory)
        return code, output.getvalue(), stub

    def test_json_and_text_show_unicode_provenance_score_and_timings(self):
        code, text, stub = self.invoke(["--query", "đơn vị token", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(text)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["results"][0]["content"], CHUNK["content"])
        self.assertIsNone(payload["results"][0]["metadata"]["source_commit"])
        self.assertEqual(payload["score_metric"], "cosine_similarity")
        self.assertTrue(stub.closed)
        self.assertEqual(set(payload["timing"]), {"startup_ms", "retrieval_ms", "total_ms"})
        code, text, _ = self.invoke(["--query", "đơn vị token"])
        self.assertEqual(code, 0)
        for expected in ("Đơn vị token", "cosine=0.7500", "workspace chưa commit", "source_reviewed", CHUNK["content"]):
            self.assertIn(expected, text)

    def test_no_match_has_distinct_status_and_exit_code(self):
        code, text, stub = self.invoke(["--query", "outside", "--json"], retriever=FakeRetriever(results=[]))
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(text)["status"], "no_match")
        self.assertIsNone(json.loads(text)["error"])
        self.assertTrue(stub.closed)

    def test_bad_arguments_fail_before_model_initialization(self):
        for arguments in (["--query", " "], ["--query", "hello", "--k", "0"],
                          ["--query", "hello", "--k", "11"], ["--query", "hello", "--k", "abc"],
                          ["--query", "hello", "--timeout-seconds", "nan"], [],
                          ["--query", "hello", "--scope", "source", "--chain-id", "1"],
                          ["--query", "hello", "--source-version", "source-v1"],
                          ["--query", "hello", "--contract-address", "0x123"]):
            with self.subTest(arguments=arguments):
                before = len(self.created)
                code, text, _ = self.invoke([*arguments, "--json"])
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(text)["status"], "invalid_query")
                self.assertEqual(len(self.created), before)

    def test_source_selection_and_ambiguous_or_unknown_versions(self):
        code, _, _ = self.invoke(["--query", "faucet", "--scope", "source", "--no-general", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(self.created[-1]["scope"], SourceScope("source-v1", include_general=False))
        self.manifest["sources"].append(dict(scope="source_only", usage="ingest", doc_version="source-v2"))
        self.write_manifest()
        for extra in ([], ["--source-version", "unknown"]):
            code, text, _ = self.invoke(["--query", "faucet", "--scope", "source", "--json", *extra])
            self.assertEqual(code, 2)
        code, _, _ = self.invoke(["--query", "faucet", "--scope", "source", "--source-version", "source-v2", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(self.created[-1]["scope"].doc_version, "source-v2")

    def test_deployment_overrides_and_disabled_general_are_preserved(self):
        self.manifest["deployment_scope"]["include_general"] = False
        self.write_manifest()
        address = "0x" + "b" * 40
        code, _, _ = self.invoke(["--query", "transfer", "--contract-address", address, "--json"])
        self.assertEqual(code, 0)
        selected = self.created[-1]["scope"]
        self.assertEqual(selected.contract_address, address)
        self.assertFalse(selected.include_general)
        self.assertEqual(selected.chain_id, 11155111)

    def test_timeout_unavailable_invalid_query_and_internal_errors_are_distinct(self):
        for error, code, status in ((RetrievalTimeout("deadline"), 5, "timeout"),
                                    (RetrievalUnavailable("index missing"), 4, "unavailable"),
                                    (InvalidQuery("encoder limit"), 2, "invalid_query"),
                                    (RuntimeError("unexpected"), 1, "internal_error")):
            with self.subTest(status=status):
                actual, text, stub = self.invoke(["--query", "hello", "--json"], retriever=FakeRetriever(error=error))
                self.assertEqual(actual, code)
                self.assertEqual(json.loads(text)["status"], status)
                self.assertTrue(stub.closed)
        code, text, _ = self.invoke(["--query", "hello", "--json"], factory_error=RetrievalUnavailable("no model"))
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(text)["status"], "unavailable")

    def test_missing_local_configuration_is_unavailable_not_no_match(self):
        (self.root / "config/rag.json").unlink()
        code, text, _ = self.invoke(["--query", "hello", "--json"])
        self.assertEqual(code, 4)
        self.assertEqual(json.loads(text)["status"], "unavailable")
        self.assertEqual(len(self.created), 0)


if __name__ == "__main__":
    unittest.main()
