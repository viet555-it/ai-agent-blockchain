"""Wallet failures keep their API contract while supporting non-HTTP consumers."""

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.error_handlers import install_wallet_handlers
from backend.services.wallet_auth import RateLimiter
from backend.wallet_errors import WalletError, WalletErrorKind
from backend.wallet_errors import fail as fail_wallet


class WalletErrorTests(unittest.TestCase):
    def test_rate_limit_is_classified_for_non_http_consumers(self):
        limiter = RateLimiter()
        limiter.check("wallet", limit=1)
        with self.assertRaises(WalletError) as caught:
            limiter.check("wallet", limit=1)
        self.assertEqual(caught.exception.kind, WalletErrorKind.RATE_LIMITED)
        self.assertEqual(caught.exception.code, "RATE_LIMIT")
        self.assertEqual(str(caught.exception), "Too many requests. Please wait.")

    def test_http_mapping_preserves_status_payload_and_private_cache_headers(self):
        cases = [
            (WalletErrorKind.INVALID_INPUT, 400, "TX_HASH", "Invalid transaction hash."),
            (
                WalletErrorKind.AUTHENTICATION_REQUIRED,
                401,
                "AUTH_REQUIRED",
                "Sign in with your wallet to continue.",
            ),
            (WalletErrorKind.PERMISSION_DENIED, 403, "ORIGIN", "Request origin is not allowed."),
            (WalletErrorKind.NOT_FOUND, 404, "NOT_FOUND", "Proposal not found."),
            (
                WalletErrorKind.CONFLICT,
                409,
                "TX_HASH",
                "Submission already has a transaction hash.",
            ),
            (WalletErrorKind.RATE_LIMITED, 429, "RATE_LIMIT", "Too many requests. Please wait."),
            (
                WalletErrorKind.DEPENDENCY_UNAVAILABLE,
                503,
                "RPC",
                "Cannot verify wallet type right now.",
            ),
        ]
        app = FastAPI()
        install_wallet_handlers(app)

        @app.get("/api/wallet-failure")
        def failure(case: int):
            kind, _, code, message = cases[case]
            fail_wallet(kind, code, message)

        with TestClient(app) as client:
            for index, (_, status, code, message) in enumerate(cases):
                with self.subTest(status=status, code=code):
                    response = client.get("/api/wallet-failure", params={"case": index})
                    self.assertEqual(response.status_code, status)
                    self.assertEqual(
                        response.json(), {"detail": {"code": code, "message": message}}
                    )
                    self.assertEqual(response.headers["cache-control"], "no-store")
                    self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f]{32}$")
