"""Bind a reviewed code/prompt followup to an existing grant without resetting usage."""

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from eval.safety_v2.live_review import fingerprint, validate_review
from eval.safety_v2.reports import atomic_write


class ContinuationLedger:
    def __init__(self, path, parent_packet, packet):
        self.path, self.parent_packet, self.packet = Path(path), parent_packet, packet
        self.review = validate_review(packet)
        parent = parent_packet["review"]
        if fingerprint(parent) != parent_packet["review_sha256"]:
            raise ValueError("Parent review integrity mismatch")
        if self.review.get("continuation_of") != parent_packet["review_sha256"]:
            raise ValueError("Followup does not name the original review")
        for field in ("provider", "model", "dataset_sha256", "tools", "execution_scope"):
            if self.review[field] != parent[field]:
                raise ValueError("Followup must preserve model, dataset, tool and execution scope")
        for field, value in parent["limits"].items():
            if field != "total_requests" and self.review["limits"][field] != value:
                raise ValueError("Followup changes an original per-request/per-case limit")
        self.case_ids = {case["id"] for case in self.review["cases"]}
        if not self.case_ids <= {case["id"] for case in parent["cases"]}:
            raise ValueError("Followup adds cases outside the original grant")
        self.lock = FileLock(str(self.path) + ".lock", timeout=5)
        self.registration = {
            "review_sha256": packet["review_sha256"],
            "case_ids": sorted(self.case_ids),
            "request_cap": self.review["limits"]["total_requests"],
        }
        with self.lock:
            state = self._read()
            registrations = state.setdefault("continuations", [])
            existing = next(
                (row for row in registrations if row["review_sha256"] == packet["review_sha256"]),
                None,
            )
            if existing:
                if any(existing[key] != value for key, value in self.registration.items()):
                    raise ValueError("Followup registration changed")
            else:
                if registrations:
                    raise ValueError(
                        "A different followup is already registered; preserve its allowance"
                    )
                if (
                    len(state["reservations"]) + self.registration["request_cap"]
                    > parent["limits"]["total_requests"]
                ):
                    raise ValueError("Followup cap exceeds remaining original grant")
                registrations.append(
                    {
                        **self.registration,
                        "starting_ordinal": len(state["reservations"]),
                        "prior_reservations_sha256": fingerprint(state["reservations"]),
                    }
                )
                self._write(state)

    def _read(self):
        # A continuation requires an existing ledger, never a replacement empty file.
        state = json.loads(self.path.read_text(encoding="utf-8"))
        parent = self.parent_packet["review"]
        if (
            state.get("review_sha256") != self.parent_packet["review_sha256"]
            or state.get("limits") != parent["limits"]
        ):
            raise ValueError("Original budget binding changed")
        records = state.get("reservations")
        ids = {case["id"] for case in parent["cases"]}
        if not isinstance(records, list) or any(
            row.get("ordinal") != i + 1 or row.get("case_id") not in ids
            for i, row in enumerate(records)
        ):
            raise ValueError("Malformed original request history")
        counts = Counter(row["case_id"] for row in records)
        if len(records) > parent["limits"]["total_requests"] or any(
            n > parent["limits"]["requests_per_case"] for n in counts.values()
        ):
            raise ValueError("Original grant is already over cap")
        for registration in state.get("continuations", []):
            prefix = records[: registration["starting_ordinal"]]
            if fingerprint(prefix) != registration["prior_reservations_sha256"]:
                raise ValueError("Earlier request history was modified")
            phase = records[registration["starting_ordinal"] :]
            if any(
                row.get("review_sha256") != registration["review_sha256"]
                or row["case_id"] not in registration["case_ids"]
                for row in phase
            ):
                raise ValueError("Unbound request in followup history")
            if len(phase) > registration["request_cap"]:
                raise ValueError("Followup history exceeds its allowance")
        return state

    def _write(self, state):
        atomic_write(self.path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")

    def snapshot(self):
        with self.lock:
            return self._read()

    def _exhausted(self, state, case_id):
        if case_id not in self.case_ids:
            raise ValueError("Case outside the reviewed followup")
        records = state["reservations"]
        phase_count = sum(
            row.get("review_sha256") == self.packet["review_sha256"] for row in records
        )
        return (
            len(records) >= state["limits"]["total_requests"]
            or sum(row["case_id"] == case_id for row in records)
            >= state["limits"]["requests_per_case"]
            or phase_count >= self.review["limits"]["total_requests"]
        )

    def exhausted(self, case_id):
        return self._exhausted(self.snapshot(), case_id)

    def reserve(self, case_id):
        with self.lock:
            state = self._read()
            if self._exhausted(state, case_id):
                raise RuntimeError("Original or followup request cap reached")
            state["reservations"].append(
                {
                    "case_id": case_id,
                    "ordinal": len(state["reservations"]) + 1,
                    "reserved_at_utc": datetime.now(UTC).isoformat(),
                    "review_sha256": self.packet["review_sha256"],
                }
            )
            self._write(state)
