"""The repository has one dotenv file, independent of the working directory."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def load_project_env() -> bool:
    """Load root .env; explicit process variables (including blank test keys) win."""
    loaded = load_dotenv(dotenv_path=ENV_FILE, override=False, encoding="utf-8")
    tokenizer_cache = os.environ.get("TIKTOKEN_CACHE_DIR")
    if tokenizer_cache and not Path(tokenizer_cache).is_absolute():
        os.environ["TIKTOKEN_CACHE_DIR"] = str((ENV_FILE.parent / tokenizer_cache).resolve())
    return loaded
