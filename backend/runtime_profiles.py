"""Explicit runtime boundaries for the phase 3 integration environment."""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from backend.network.config import DEFAULT_NETWORKS, ChainConfig


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    chain_id: int

    @classmethod
    def load(cls, name: str | None = None, *, allow_sepolia_write: bool = False) -> "RuntimeProfile":
        name = name or os.environ.get("PHASE3_PROFILE", "local_evm")
        chains = {"unit": 31337, "local_evm": 31337, "sepolia_read": 11155111}
        if name == "sepolia_write":
            if allow_sepolia_write:
                return cls(name, 11155111)
            raise ValueError(
                "sepolia_write requires explicit execution authorization (G3.2 gates)"
            )
        if name not in chains:
            raise ValueError(f"Unknown runtime profile: {name}")
        return cls(name, chains[name])

    def network(self) -> ChainConfig:
        config = DEFAULT_NETWORKS[self.chain_id].model_copy(deep=True)
        if self.chain_id == 31337:
            rpc = os.environ.get("LOCAL_RPC_URL", "http://127.0.0.1:8545")
            parsed = urlparse(rpc)
            if (
                parsed.scheme != "http"
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Local profiles require an HTTP loopback RPC without credentials")
            config.rpc_urls = [rpc]
            config.fallback_rpc_urls = []
        return config


def isolated_test_environment() -> dict[str, str]:
    """Blank known credentials so dotenv cannot restore a testnet signer/key."""
    env = dict(os.environ)
    for name in (
        "SIGNER_PRIVATE_KEY",
        "WALLET_PRIVATE_KEY",
        "PRIVATE_KEY",
        "GEMINI_API_KEY",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "ETHERSCAN_API_KEY",
        "SEPOLIA_RPC_URL",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
    ):
        env[name] = ""
    env.update(
        PHASE3_PROFILE="local_evm",
        PHASE3_LOCAL_WRITES="false",
        PHASE3_AGENT="legacy",
        DEFAULT_CHAIN_ID="31337",
        LLM_PROVIDER="fake",
        LLM_MODEL="",
        DRY_RUN="true",
        LOCAL_RPC_URL="http://127.0.0.1:8545",
        LOCAL_TEST_RPC="http://127.0.0.1:8545",
        PYTHONUTF8="1",
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
    )
    return env
