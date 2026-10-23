import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(importlib.util.find_spec("chromadb"), "Install the locked RAG environment for Chroma integration tests")
class IndexIntegrationTest(unittest.TestCase):
    def scenario(self, command, path):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("p4_index_scenario.py")), command, str(path)],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
            capture_output=True, text=True, encoding="utf-8", timeout=90,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_ingest_update_delete_rollback_and_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.scenario("lifecycle", directory)
            self.assertTrue(report["update_delete"])
            self.assertTrue(report["unchanged"])
            self.assertTrue(self.scenario("reopen", directory)["reopened"])

    def test_failed_build_and_model_mismatch_leave_valid_active_index(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.scenario("failures", directory)
            self.assertTrue(all(report.values()))


if __name__ == "__main__":
    unittest.main()
