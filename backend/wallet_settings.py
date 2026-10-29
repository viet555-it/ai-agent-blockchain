"""Explicit feature flags and origin boundary for browser-wallet sessions."""

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class WalletSettings:
    database_url: str
    origin: str = "http://127.0.0.1:8000"
    browser_writes: bool = False
    session_seconds: int = 28800
    challenge_seconds: int = 300
    finality_confirmations: int = 12

    def __post_init__(self):
        parsed = urlparse(self.origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
        ):
            raise ValueError("APP_ORIGIN must be a scheme and host only")
        if parsed.scheme != "https" and parsed.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }:
            raise ValueError("Wallet authentication requires HTTPS outside local development")
        if self.finality_confirmations < 1:
            raise ValueError("Finality confirmations must be positive")

    @classmethod
    def from_environment(cls):
        return cls(
            database_url=os.environ.get(
                "DATABASE_URL", "sqlite:///" + (ROOT / "data/app.db").as_posix()
            ),
            origin=os.environ.get("APP_ORIGIN", "http://127.0.0.1:8000").rstrip("/"),
            browser_writes=os.environ.get("BROWSER_WALLET_WRITES", "false").lower() == "true",
        )
