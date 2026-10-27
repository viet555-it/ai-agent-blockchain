"""Durable request reservations for the user's single G3.5 Gemini grant."""

import json
import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

LIMITS = {"dev": 75, "safety": 50, "holdout": 75}


class RequestBudget:
    def __init__(self, path: Path, limits=None):
        self.path = path
        self.limits = dict(LIMITS if limits is None else limits)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(path) + ".lock", timeout=5)

    def snapshot(self):
        if not self.path.exists():
            return {"limits": self.limits, "reservations": []}
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if state.get("limits") != self.limits or not isinstance(state.get("reservations"), list):
            raise RuntimeError("Gemini request ledger mismatch; do not reset it")
        return state

    def reserve(self, phase):
        with self.lock:
            state = self.snapshot()
            if (
                phase not in self.limits
                or sum(row["phase"] == phase for row in state["reservations"]) >= self.limits[phase]
                or len(state["reservations"]) >= sum(self.limits.values())
            ):
                raise RuntimeError("Approved G3.5 generation budget reached")
            state["reservations"].append(
                {
                    "phase": phase,
                    "reserved_at_utc": datetime.now(UTC).isoformat(),
                    "ordinal": len(state["reservations"]) + 1,
                }
            )
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as stream:
                temporary = Path(stream.name)
                json.dump(state, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            for attempt in range(6):
                try:
                    os.replace(temporary, self.path)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.1 * (attempt + 1))
