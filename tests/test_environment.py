"""Root dotenv behavior: cwd independence, precedence and test isolation."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from config.environment import ENV_FILE, PROJECT_ROOT, load_project_env
from config.settings import Settings
from rag.settings import RAGSettings


class RootEnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.env = self.root / ".env"
        self.child = self.root / "contracts"
        self.child.mkdir()
        self.addCleanup(os.chdir, Path.cwd())
        os.chdir(self.child)

    def test_python_loads_only_root_and_preserves_blank_process_overrides(self):
        self.env.write_text("LLM_MODEL=root-model\nGEMINI_API_KEY=dummy-fixture\n")
        (self.child / ".env").write_text("LLM_MODEL=wrong-cwd-model\n")
        with (
            patch("config.environment.ENV_FILE", self.env),
            patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=True),
        ):
            load_project_env()
            self.assertEqual(os.environ["LLM_MODEL"], "root-model")
            self.assertEqual(os.environ["GEMINI_API_KEY"], "")

    def test_settings_default_is_absolute_root_dotenv(self):
        self.assertEqual(Settings.model_config["env_file"], ENV_FILE)
        self.assertEqual(ENV_FILE, PROJECT_ROOT / ".env")
        self.assertTrue(ENV_FILE.is_absolute())

    def test_relative_tokenizer_cache_resolves_from_root_not_working_directory(self):
        self.env.write_text("TIKTOKEN_CACHE_DIR=.phase3/tiktoken\n")
        with patch("config.environment.ENV_FILE", self.env), patch.dict(os.environ, {}, clear=True):
            load_project_env()
            self.assertEqual(Path(os.environ["TIKTOKEN_CACHE_DIR"]), self.root / ".phase3/tiktoken")

    def test_local_setup_cli_uses_rpc_from_root_dotenv(self):
        from scripts import setup_local_demo

        self.env.write_text("LOCAL_RPC_URL=http://127.0.0.1:8549\n")
        with (
            patch("config.environment.ENV_FILE", self.env),
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["setup_local_demo"]),
            patch.object(setup_local_demo, "setup", return_value={}) as setup,
            redirect_stdout(StringIO()),
        ):
            setup_local_demo.main()
        setup.assert_called_once_with("http://127.0.0.1:8549")

    def test_rag_reads_root_paths_without_exporting_credentials(self):
        config = self.root / "config/rag.json"
        config.parent.mkdir()
        config.write_text((PROJECT_ROOT / "config/rag.json").read_text())
        self.env.write_text(
            "RAG_INDEX_PATH=chosen-index\nRAG_CACHE_PATH=chosen-cache\nGEMINI_API_KEY=dummy-fixture\n"
        )
        (self.child / ".env").write_text("RAG_INDEX_PATH=wrong-cwd-index\n")
        with patch.dict(os.environ, {}, clear=True):
            settings = RAGSettings.load(config, root=self.root)
            self.assertEqual(settings.index_dir, self.root / "chosen-index")
            self.assertEqual(settings.cache_dir, self.root / "chosen-cache")
            self.assertNotIn("GEMINI_API_KEY", os.environ)
        with patch.dict(os.environ, {"RAG_INDEX_PATH": "process-index"}, clear=True):
            self.assertEqual(
                RAGSettings.load(config, root=self.root).index_dir, self.root / "process-index"
            )

    @unittest.skipUnless(shutil.which("node"), "Node is needed for Hardhat config loading")
    def test_hardhat_reads_parent_root_not_contracts_dotenv(self):
        self.env.write_text(
            "SEPOLIA_RPC_URL=http://root-fixture.invalid\nPRIVATE_KEY=dummy-fixture\n"
        )
        (self.child / ".env").write_text("SEPOLIA_RPC_URL=http://wrong-cwd.invalid\n")
        config = self.child / "hardhat.config.js"
        config.write_text((PROJECT_ROOT / "contracts/hardhat.config.js").read_text())
        code = """const Module = require('module'); const original = Module._load;
Module._load = function(name, ...args) { if(name === '@nomicfoundation/hardhat-toolbox') return {}; return original.call(this,name,...args); };
const config = require('./hardhat.config.js'); console.log(JSON.stringify({url:config.networks.sepolia.url,accounts:config.networks.sepolia.accounts}));"""
        env = {
            **os.environ,
            "NODE_PATH": str(PROJECT_ROOT / "contracts/node_modules"),
            "PRIVATE_KEY": "",
        }
        env.pop("SEPOLIA_RPC_URL", None)
        result = subprocess.run(
            [shutil.which("node"), "-e", code],
            cwd=self.child,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout), {"url": "http://root-fixture.invalid", "accounts": []}
        )
