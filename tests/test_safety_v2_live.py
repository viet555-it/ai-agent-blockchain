"""Exercise the live path using injected providers; no Gemini SDK/network is constructed."""

import copy
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.llm.base import LLMResponse, ToolCall
from eval.safety_v2.live import grade_agent, run_live_evaluation
from eval.safety_v2.live_review import build_review
from eval.safety_v2.runner import load_dataset
from eval.safety_v2.runtime import fixture_clock
from scripts.evaluate_safety_v2_live import main


class Provider:
    _model = "test-model"
    _max_output_tokens = 512

    def __init__(self, responses=None, failure=False):
        self.responses = list(responses or [LLMResponse(content="Hello.")])
        self.call_count = 0
        self.failure = failure
        self.closed = False

    async def chat(self, messages, tools):
        self.call_count += 1
        if self.failure:
            raise RuntimeError("provider test failure")
        return self.responses.pop(0)

    async def aclose(self):
        self.closed = True


def execute(tmp_path, packet, provider, ids):
    return run_live_evaluation(
        packet,
        approved_hash=packet["review_sha256"],
        allow_live=True,
        provider_factory=lambda: provider,
        case_ids=ids,
        output_root=tmp_path / "runs",
        ledger_path=tmp_path / "budget.json",
    )


def test_live_gates_run_before_provider_construction(tmp_path):
    packet = build_review("test-model")
    for kwargs in (
        {"approved_hash": packet["review_sha256"]},
        {"approved_hash": "wrong", "allow_live": True},
    ):
        with patch("agent.llm.gemini.GeminiProvider") as factory, pytest.raises(ValueError):
            run_live_evaluation(packet, output_root=tmp_path, **kwargs)
        factory.assert_not_called()
    with (
        patch("agent.llm.gemini.GeminiProvider") as factory,
        pytest.raises(ValueError, match="GEMINI_API_KEY"),
    ):
        run_live_evaluation(
            packet, approved_hash=packet["review_sha256"], allow_live=True, output_root=tmp_path
        )
    factory.assert_not_called()


def test_cli_missing_consent_does_not_load_credentials():
    with (
        patch(
            "sys.argv",
            ["evaluate", "--review", "not-read.json", "--approved-review-hash", "not-used"],
        ),
        patch("scripts.evaluate_safety_v2_live.load_project_env") as load,
        pytest.raises(SystemExit),
    ):
        main()
    load.assert_not_called()


def test_live_turn_uses_real_proposal_guard_and_closes_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(Path(".phase3/tiktoken").resolve()))
    packet = build_review("test-model")
    provider = Provider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="one",
                        name="transfer_eth",
                        arguments={
                            "to": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
                            "value_eth": "0.1",
                        },
                    )
                ]
            )
        ]
    )
    directory, report = execute(tmp_path, packet, provider, ["V2-07"])
    (row,) = report["results"]
    assert row["passed"] is True
    assert row["agent_observed"]["decision"] == "REQUIRE_APPROVAL"
    assert row["safety_passed"] is True
    assert report["summaries"]["live_agent"]["scripted_agent_cases"] == 0
    assert report["summaries"]["live_agent"]["live_agent_cases"] == 1
    assert report["live_provider_requests"] == 0
    assert report["provider_request_reservations_this_run"] == provider.call_count == 1
    assert provider.closed
    assert (
        json.loads((directory / "results.json").read_text(encoding="utf-8"))["provider"]
        == "injected_test_double"
    )


def test_text_only_refusal_is_manual_review_not_automatic_success(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(Path(".phase3/tiktoken").resolve()))
    _, report = execute(tmp_path, build_review("test-model"), Provider(), ["V2-33"])
    (row,) = report["results"]
    assert row["status"] == "manual_review" and row["passed"] is None
    assert row["policy_passed"] is True  # Independent direct policy still ran.
    assert report["summaries"]["live_agent"]["manual_review"] == 1
    assert report["summaries"]["live_agent"]["passed"] == 0


def test_reviewed_read_tool_roundtrip_consumes_two_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(Path(".phase3/tiktoken").resolve()))
    provider = Provider(
        [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id="read",
                        name="get_native_balance",
                        arguments={"address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"},
                    )
                ]
            ),
            LLMResponse(content="Balance read completed."),
        ]
    )
    _, report = execute(tmp_path, build_review("test-model"), provider, ["V2-05"])
    assert report["results"][0]["passed"] is True
    assert provider.call_count == report["provider_request_reservations_this_run"] == 2
    assert provider.closed


def test_provider_failure_is_checkpointed_and_budget_exhaustion_skips_factory(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(Path(".phase3/tiktoken").resolve()))
    packet = build_review("test-model", request_cap=1)
    provider = Provider(failure=True)
    _, report = execute(tmp_path, packet, provider, ["V2-01", "V2-02"])
    assert [row["status"] for row in report["results"]] == ["error", "not_run"]
    assert provider.closed and provider.call_count == 1
    assert len(report["request_reservations"]["reservations"]) == 1
    assert report["summaries"]["live_agent"]["passed"] == 0


def test_fixture_clock_does_not_change_network_wall_clock():
    before = time.time()
    with fixture_clock(1):
        assert time.time() >= before
        from backend.services.wallet import submissions

        assert submissions.time.time() == 1


def test_text_claiming_execution_fails_and_workflow_is_not_credited_to_llm():
    cases = load_dataset()[0]
    events = [{"type": "final", "data": {"content": "I have sent the transfer."}}]
    observed, passed, manual = grade_agent(cases[6], events, [])
    assert observed["false_execution_claim"] and passed is False and manual is None
    _, passed, manual = grade_agent(
        cases[30], [{"type": "final", "data": {"content": "Please confirm."}}], []
    )
    assert passed is None and manual == "WORKFLOW_NOT_EXERCISED_BY_LIVE_TURN"


def test_changed_review_is_rejected_without_network(tmp_path):
    packet = copy.deepcopy(build_review("test-model"))
    packet["review"]["model"] = "modified"
    with patch("agent.llm.gemini.GeminiProvider") as factory, pytest.raises(ValueError):
        run_live_evaluation(
            packet, approved_hash=packet["review_sha256"], allow_live=True, output_root=tmp_path
        )
    factory.assert_not_called()


def test_rate_limit_is_recorded_and_stops_future_calls_without_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", str(Path(".phase3/tiktoken").resolve()))
    packet = build_review("test-model")
    provider = Provider(failure=True)
    provider.last_error = {
        "http_status": 429,
        "reason": "PROVIDER_HTTP_ERROR",
        "private": "must-not-be-recorded",
    }
    _, report = execute(tmp_path, packet, provider, ["V2-01", "V2-02"])
    first, second = report["results"]
    assert first["status"] == "error"
    assert first["diagnostic"] == {"http_status": 429, "reason": "PROVIDER_HTTP_ERROR"}
    assert second["status"] == "not_run" and second["error_type"] == "PROVIDER_RATE_LIMIT"
    assert provider.call_count == 1 and provider.closed
    assert "must-not-be-recorded" not in json.dumps(report)
