"""Canonical hashes and JSON conversion used by approval and receipt records."""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from web3 import Web3


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return Web3.to_hex(value)
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value
