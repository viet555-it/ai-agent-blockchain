"""Wallet identifiers, capabilities and RPC scalar conversion."""

import hashlib
import secrets
import uuid

from web3 import Web3


def uid():
    return str(uuid.uuid4())


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def token():
    return secrets.token_urlsafe(32)


def number(value):
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)


def hexdata(value):
    if value is None:
        return "0x"
    return value.lower() if isinstance(value, str) else Web3.to_hex(value).lower()
