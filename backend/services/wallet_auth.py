"""EOA login using an exact, server-issued ERC-4361 message (no arbitrary message parsing)."""

import secrets
import time
from collections import OrderedDict
from datetime import UTC, datetime
from threading import Lock
from urllib.parse import urlparse

from eth_account import Account
from eth_account.messages import encode_defunct
from fastapi import HTTPException
from sqlalchemy import select, update
from web3 import Web3

from backend.db.schema_v1 import challenges, sessions, wallets
from backend.services.wallet_common import (
    Principal,
    fail,
    hashed,
    one,
    record_audit,
    revoke_contexts,
    token,
    uid,
)

SESSION_COOKIE = "ati_session"
CSRF_COOKIE = "ati_csrf"
BINDING_COOKIE = "ati_browser"


class RateLimiter:
    def __init__(self):
        self.entries = OrderedDict()
        self.lock = Lock()

    def check(self, key, limit=20, seconds=60):
        now = time.monotonic()
        with self.lock:
            times = [value for value in self.entries.pop(key, []) if value > now - seconds]
            if len(times) >= limit:
                self.entries[key] = times
                fail(429, "RATE_LIMIT", "Too many requests. Please wait.")
            self.entries[key] = [*times, now]
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)


class WalletAuth:
    def __init__(self, database, settings, chain_id, blockchain):
        self.db, self.settings, self.chain_id, self.blockchain = (
            database,
            settings,
            chain_id,
            blockchain,
        )
        self.limiter = RateLimiter()

    def origin(self, request):
        if request.headers.get("origin") != self.settings.origin:
            fail(403, "ORIGIN", "Request origin is not allowed.")

    def cookie(self, response, key, value, *, httponly=True, age=None):
        response.set_cookie(
            key,
            value,
            max_age=age or self.settings.session_seconds,
            httponly=httponly,
            secure=self.settings.origin.startswith("https:"),
            samesite="strict",
            path="/",
        )

    def challenge(self, request, response, address, chain_id):
        self.origin(request)
        self.limiter.check(("challenge", request.client.host if request.client else "unknown"))
        if not Web3.is_address(address) or chain_id != self.chain_id:
            fail(400, "WALLET_NETWORK", "Invalid address or unsupported network.")
        address = Web3.to_checksum_address(address)
        binding = request.cookies.get(BINDING_COOKIE) or token()
        self.cookie(response, BINDING_COOKIE, binding)
        now = time.time()
        expires = now + self.settings.challenge_seconds

        def stamp(value):
            return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")

        nonce = secrets.token_hex(16)
        message = (
            f"{urlparse(self.settings.origin).netloc} wants you to sign in with your Ethereum account:\n"
            f"{address}\n\nSign in to your private AI Agent history. No transaction will be sent.\n\n"
            f"URI: {self.settings.origin}\nVersion: 1\nChain ID: {self.chain_id}\n"
            f"Nonce: {nonce}\nIssued At: {stamp(now)}\nExpiration Time: {stamp(expires)}"
        )
        challenge_id = uid()
        with self.db.transaction() as connection:
            connection.execute(
                challenges.insert().values(
                    id=challenge_id,
                    address=address,
                    message=message,
                    binding_hash=hashed(binding),
                    expires_at=expires,
                )
            )
        return {"challenge_id": challenge_id, "message": message, "expires_at": expires}

    def verify(self, request, response, challenge_id, signature):
        self.origin(request)
        self.limiter.check(("verify", request.client.host if request.client else "unknown"))
        with self.db.transaction() as connection:
            challenge = one(connection, select(challenges).where(challenges.c.id == challenge_id))
        if (
            not challenge
            or challenge["consumed_at"]
            or challenge["expires_at"] <= time.time()
            or not secrets.compare_digest(
                challenge["binding_hash"], hashed(request.cookies.get(BINDING_COOKIE, ""))
            )
        ):
            fail(401, "CHALLENGE", "Login challenge is invalid or expired.")
        try:
            recovered = Account.recover_message(
                encode_defunct(text=challenge["message"]), signature=signature
            )
        except Exception:
            fail(401, "SIGNATURE", "Invalid login signature.")
        if recovered.lower() != challenge["address"].lower():
            fail(401, "SIGNATURE", "Signature does not match this wallet.")
        # EOA only; never silently apply EOA verification to a contract account.
        try:
            if self.blockchain.w3.eth.get_code(recovered):
                fail(
                    400, "UNSUPPORTED_WALLET", "Contract wallets are not supported in this version."
                )
        except HTTPException:
            raise
        except Exception:
            fail(503, "RPC", "Cannot verify wallet type right now.")
        raw, csrf = token(), token()
        now, session_id = time.time(), uid()
        with self.db.transaction() as connection:
            consumed = connection.execute(
                update(challenges)
                .where(
                    challenges.c.id == challenge_id,
                    challenges.c.consumed_at.is_(None),
                    challenges.c.expires_at > now,
                )
                .values(consumed_at=now)
            )
            if consumed.rowcount != 1:
                fail(401, "CHALLENGE", "Login challenge has already been used.")
            existing = one(
                connection, select(wallets).where(wallets.c.address == recovered.lower())
            )
            if not existing:
                existing = {"id": uid(), "address": recovered.lower(), "created_at": now}
                connection.execute(wallets.insert().values(**existing))
            old = one(
                connection,
                select(sessions).where(
                    sessions.c.token_hash == hashed(request.cookies.get(SESSION_COOKIE, ""))
                ),
            )
            if old:
                revoke_contexts(connection, old["id"])
                connection.execute(
                    update(sessions).where(sessions.c.id == old["id"]).values(revoked_at=now)
                )
            connection.execute(
                sessions.insert().values(
                    id=session_id,
                    wallet_id=existing["id"],
                    token_hash=hashed(raw),
                    csrf_hash=hashed(csrf),
                    created_at=now,
                    expires_at=now + self.settings.session_seconds,
                )
            )
            record_audit(connection, existing["id"], "LOGIN")
        self.cookie(response, SESSION_COOKIE, raw)
        self.cookie(response, CSRF_COOKIE, csrf, httponly=False)
        return {"address": recovered, "expires_at": now + self.settings.session_seconds}

    def principal(self, request):
        with self.db.transaction() as connection:
            row = one(
                connection,
                select(sessions, wallets.c.address)
                .join(wallets)
                .where(
                    sessions.c.token_hash == hashed(request.cookies.get(SESSION_COOKIE, "")),
                    sessions.c.revoked_at.is_(None),
                    sessions.c.expires_at > time.time(),
                ),
            )
        if not row:
            fail(401, "AUTH_REQUIRED", "Sign in with your wallet to continue.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            self.origin(request)
            if not secrets.compare_digest(
                row["csrf_hash"], hashed(request.headers.get("x-csrf-token", ""))
            ):
                fail(403, "CSRF", "Request verification failed.")
            self.limiter.check(("write", row["wallet_id"]), limit=60)
        return Principal(row["id"], row["wallet_id"], Web3.to_checksum_address(row["address"]))

    def logout(self, request, response):
        principal = self.principal(request)
        with self.db.transaction() as connection:
            revoke_contexts(connection, principal.session_id)
            connection.execute(
                update(sessions)
                .where(sessions.c.id == principal.session_id)
                .values(revoked_at=time.time())
            )
            record_audit(connection, principal.wallet_id, "LOGOUT")
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return {"status": "SIGNED_OUT"}
