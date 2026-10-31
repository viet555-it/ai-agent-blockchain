"""A code/prompt followup must not erase earlier charges or gain another global cap."""

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from eval.safety_v2.continuation import ContinuationLedger
from eval.safety_v2.live_review import LiveRequestLedger, build_review


def packets(parent_cap=8, child_cap=2):
    parent = build_review("test-model", request_cap=parent_cap)
    child = build_review(
        "test-model",
        request_cap=child_cap,
        case_ids=["V2-01", "V2-02"],
        continuation_of=parent["review_sha256"],
    )
    return parent, child


def test_continuation_preserves_parent_records_and_charges_same_file(tmp_path):
    parent, child = packets()
    path = tmp_path / "ledger.json"
    old = LiveRequestLedger(path, parent)
    old.reserve("V2-01")
    prefix = copy.deepcopy(old.snapshot()["reservations"])
    ledger = ContinuationLedger(path, parent, child)
    ledger.reserve("V2-01")
    resumed = ContinuationLedger(path, parent, child)
    resumed.reserve("V2-02")
    assert resumed.snapshot()["reservations"][:1] == prefix
    assert len(resumed.snapshot()["reservations"]) == 3
    assert resumed.snapshot()["review_sha256"] == parent["review_sha256"]
    assert resumed.exhausted("V2-01")
    with pytest.raises(RuntimeError):
        resumed.reserve("V2-01")


def test_original_per_case_cap_survives_new_review(tmp_path):
    parent, child = packets(parent_cap=8, child_cap=2)
    path = tmp_path / "ledger.json"
    old = LiveRequestLedger(path, parent)
    for _ in range(4):
        old.reserve("V2-01")
    ledger = ContinuationLedger(path, parent, child)
    assert ledger.exhausted("V2-01")
    with pytest.raises(RuntimeError):
        ledger.reserve("V2-01")
    ledger.reserve("V2-02")


def test_followup_cannot_overallocate_remaining_global_grant(tmp_path):
    parent, child = packets(parent_cap=2, child_cap=2)
    path = tmp_path / "ledger.json"
    old = LiveRequestLedger(path, parent)
    old.reserve("V2-01")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="remaining"):
        ContinuationLedger(path, parent, child)
    assert path.read_bytes() == before


def test_concurrent_followup_reservations_respect_phase_cap(tmp_path):
    parent, child = packets(child_cap=1)
    path = tmp_path / "ledger.json"
    LiveRequestLedger(path, parent).reserve("V2-03")
    ledger = ContinuationLedger(path, parent, child)

    def worker(case_id):
        try:
            ContinuationLedger(path, parent, child).reserve(case_id)
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(worker, ["V2-01", "V2-02"])) == [False, True]
    assert len(ledger.snapshot()["reservations"]) == 2


def test_parent_tampering_or_missing_history_fails_closed(tmp_path):
    parent, child = packets()
    path = tmp_path / "ledger.json"
    with pytest.raises(FileNotFoundError):
        ContinuationLedger(path, parent, child)
    LiveRequestLedger(path, parent).reserve("V2-01")
    ledger = ContinuationLedger(path, parent, child)
    state = ledger.snapshot()
    state["reservations"][0]["case_id"] = "V2-02"
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="history"):
        ledger.reserve("V2-01")


def test_model_or_case_scope_cannot_expand(tmp_path):
    parent, child = packets()
    path = tmp_path / "ledger.json"
    LiveRequestLedger(path, parent).reserve("V2-01")
    other = build_review(
        "another-model", request_cap=2, case_ids=["V2-01"], continuation_of=parent["review_sha256"]
    )
    with pytest.raises(ValueError, match="model"):
        ContinuationLedger(path, parent, other)
    ledger = ContinuationLedger(path, parent, child)
    with pytest.raises(ValueError, match="outside"):
        ledger.reserve("V2-03")
