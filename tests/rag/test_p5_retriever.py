import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(importlib.util.find_spec("chromadb"), "Use the locked RAG environment for Chroma tests")
class RetrievalIntegrationTest(unittest.TestCase):
    def test_scope_signature_cosine_nohit_context_and_error_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("p5_retrieval_scenario.py")), directory],
                cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT)},
                capture_output=True, text=True, encoding="utf-8", timeout=90,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            report = json.loads(result.stdout.strip().splitlines()[-1])
            self.assertTrue(all(report.values()))


if __name__ == "__main__":
    unittest.main()
