"""Application settings – reads from .env + config YAML files.

All secrets come from environment variables only. Config files (policy.yaml,
tools.yaml) are loaded from the ``config/`` directory relative to the project root.
"""

from __future__ import annotations

import json
import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
ABIS_DIR = PROJECT_ROOT / "abis"


class LLMProviderName(StrEnum):
    """Supported LLM providers."""

    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    FAKE = "fake"


class Settings(BaseSettings):
    """Central application settings, loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ────────────────────────────────────────────────────────────
    llm_provider: LLMProviderName = LLMProviderName.GEMINI
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_model: str = ""  # empty → provider default

    # ── Blockchain ─────────────────────────────────────────────────────
    sepolia_rpc_url: str = "https://rpc.sepolia.org"
    wallet_private_key: str = ""  # NEVER log this
    etherscan_api_key: str = ""

    # ── Security ───────────────────────────────────────────────────────
    dry_run: bool = True
    max_steps: int = Field(default=10, ge=1, le=50)

    # ── Memory ─────────────────────────────────────────────────────────
    max_context_tokens: int = Field(default=8000, ge=1000)
    token_budget_buffer: float = Field(default=0.2, ge=0.0, le=0.5)

    @field_validator("wallet_private_key")
    @classmethod
    def _mask_private_key_log(cls, v: str) -> str:
        """Private key is accepted as-is but we ensure it is not empty string logged."""
        return v  # validation only; actual masking is in __repr__

    def __repr__(self) -> str:
        """Mask sensitive fields in repr."""
        safe = {
            k: ("***" if "key" in k.lower() or "private" in k.lower() else v)
            for k, v in self.model_dump().items()
        }
        return f"Settings({safe})"

    @property
    def effective_token_budget(self) -> int:
        """Token budget after applying safety buffer (e.g. 8000 * 0.8 = 6400)."""
        return int(self.max_context_tokens * (1.0 - self.token_budget_buffer))


# ── YAML config loaders ───────────────────────────────────────────────


def load_yaml_config(filename: str) -> dict[str, Any]:
    """Load a YAML config file from the config/ directory."""
    path = CONFIG_DIR / filename
    if not path.exists():
        logger.warning("Config file not found: %s – using empty config", path)
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_policy_config() -> dict[str, Any]:
    """Load policy.yaml."""
    return load_yaml_config("policy.yaml")


def load_tools_config() -> dict[str, Any]:
    """Load tools.yaml."""
    return load_yaml_config("tools.yaml")


def load_abi(filename: str) -> list[dict[str, Any]]:
    """Load an ABI JSON file from the abis/ directory."""
    path = ABIS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"ABI file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Singleton-like accessor ───────────────────────────────────────────

_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the global Settings instance."""
    global _settings  # noqa: PLW0603
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Reset settings (for testing)."""
    global _settings  # noqa: PLW0603
    _settings = None
