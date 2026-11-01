"""Payload scope and durable budgets verified without constructing a network client."""

import asyncio
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from agent.llm.base import LLMResponse
from eval.safety_v2.live_review import (
    LiveRequestLedger,
    ReviewedProvider,
    build_review,
    validate_review,
    write_review,
)


class Counter:
    def count_messages(self, messages):
        return 100

    def count(self, text):
        return 100


class Provider:
    _model = "test-model"
    _max_output_tokens = 512

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, tools):
        self.calls += 1
        return LLMResponse(content="Test response")


def test_review_contains_only_intended_inputs_and_matches_scope(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "private-canary-not-for-payload")
    packet = build_review("test-model")
    review = validate_review(packet)
    assert len(review["cases"]) == 40
    assert len(review["tools"]) == 9
    text = json.dumps(packet)
    assert "private-canary-not-for-payload" not in text
    assert "expected_policy_decision" not in text
    assert "agent_outcomes_allowed" not in text
    assert all(set(case) == {"id", "initial_messages"} for case in review["cases"])
    write_review(tmp_path, packet)
    assert len((tmp_path / "payload-preview.jsonl").read_text(encoding="utf-8").splitlines()) == 40
    assert not (tmp_path / "budget.json").exists()


def test_modified_packet_and_changed_sources_require_new_review():
    packet = build_review("test-model")
    modified = copy.deepcopy(packet)
    modified["review"]["limits"]["total_requests"] = 160
    with pytest.raises(ValueError, match="integrity"):
        validate_review(modified)
    with (
        patch(
            "eval.safety_v2.live_review.source_manifest", return_value={"changed.py": "different"}
        ),
        pytest.raises(ValueError, match="changed"),
    ):
        validate_review(packet)


def test_global_request_budget_survives_restart_and_reserves_before_errors(tmp_path):
    packet = build_review("test-model", request_cap=2)
    path = tmp_path / "budget.json"
    ledger = LiveRequestLedger(path, packet)
    ledger.reserve("V2-01")
    LiveRequestLedger(path, packet).reserve("V2-02")
    with pytest.raises(RuntimeError, match="cap"):
        LiveRequestLedger(path, packet).reserve("V2-03")
    assert len(ledger.snapshot()["reservations"]) == 2


def test_per_case_cap_and_concurrent_workers_cannot_exceed_global_cap(tmp_path):
    packet = build_review("test-model", request_cap=8)
    ledger = LiveRequestLedger(tmp_path / "per-case.json", packet)
    for _ in range(4):
        ledger.reserve("V2-01")
    with pytest.raises(RuntimeError):
        ledger.reserve("V2-01")
    packet = build_review("test-model", request_cap=1)
    path = tmp_path / "concurrent.json"

    def worker(case_id):
        try:
            LiveRequestLedger(path, packet).reserve(case_id)
            return True
        except RuntimeError:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(worker, ["V2-01", "V2-02"])) == [False, True]


def test_provider_refuses_changed_messages_schemas_and_estimated_token_overflow(tmp_path):
    packet = build_review("test-model")
    ledger = LiveRequestLedger(tmp_path / "budget.json", packet)
    inner = Provider()
    provider = ReviewedProvider(inner, ledger, "V2-01", Counter())
    messages = packet["review"]["cases"][0]["initial_messages"]
    tools = packet["review"]["tools"]
    with pytest.raises(ValueError, match="scope"):
        asyncio.run(provider.chat([*messages, {"role": "user", "content": "unreviewed"}], tools))
    with pytest.raises(ValueError, match="schema"):
        asyncio.run(provider.chat(messages, []))
    with (
        patch.object(provider.counter, "count", return_value=10000),
        pytest.raises(ValueError, match="token"),
    ):
        asyncio.run(provider.chat(messages, tools))
    assert inner.calls == 0
    assert ledger.snapshot()["reservations"] == []


def test_success_and_provider_failure_both_consume_reservation(tmp_path):
    packet = build_review("test-model", request_cap=2)
    ledger = LiveRequestLedger(tmp_path / "budget.json", packet)
    inner = Provider()
    provider = ReviewedProvider(inner, ledger, "V2-01", Counter())
    messages = packet["review"]["cases"][0]["initial_messages"]
    tools = packet["review"]["tools"]
    assert asyncio.run(provider.chat(messages, tools)).content == "Test response"

    async def fail(**kwargs):
        raise RuntimeError("Provider unavailable")

    with patch.object(inner, "chat", side_effect=fail), pytest.raises(RuntimeError):
        asyncio.run(provider.chat(messages, tools))
    assert len(ledger.snapshot()["reservations"]) == 2
    with pytest.raises(RuntimeError, match="cap"):
        asyncio.run(provider.chat(messages, tools))
    assert inner.calls == 1


def test_provider_settings_and_different_review_cannot_reuse_allowance(tmp_path):
    packet = build_review("test-model")
    ledger = LiveRequestLedger(tmp_path / "budget.json", packet)
    inner = Provider()
    inner._max_output_tokens = 1024
    with pytest.raises(ValueError, match="settings"):
        ReviewedProvider(inner, ledger, "V2-01", Counter())
    ledger.reserve("V2-01")
    other = build_review("another-model")
    with pytest.raises(ValueError, match="mismatch"):
        LiveRequestLedger(ledger.path, other).reserve("V2-01")
