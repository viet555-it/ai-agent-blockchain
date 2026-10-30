"""Measured LLM adapter with fake scripts, local previews and durable request reservations."""

from __future__ import annotations

import json
import time

from agent.llm.base import LLMResponse, ToolCall
from agent.llm.fake import FakeLLMProvider


class MeasuredProvider:
    def __init__(self, inner=None):
        self.inner = inner
        self.timings = []
        self.preview_path = None
        self.preview_case = None
        self.model = ""
        self.live_budget = None
        self.budget_phase = None

    @property
    def last_error(self):
        return getattr(self.inner, "last_error", None)

    def scripted(self, case, *, safety=False):
        if safety:
            calls = [case["scripted_attack"]]
            script = []
            if case["fault"] == "tool_injection":
                script.append(
                    LLMResponse(
                        tool_calls=[
                            ToolCall(
                                id="read",
                                name="get_native_balance",
                                arguments={"address": case["bindings"]["wallet"]},
                            )
                        ]
                    )
                )
            script.extend(
                [
                    LLMResponse(
                        tool_calls=[
                            ToolCall(id="attack", name=row["tool"], arguments=row["args"])
                            for row in calls
                        ]
                    ),
                    LLMResponse(content="No transaction has been sent."),
                ]
            )
        else:
            calls = case["expected"]["calls"]
            script = (
                [
                    LLMResponse(
                        tool_calls=[
                            ToolCall(id=f"call-{i}", name=row["tool"], arguments=row["args"])
                            for i, row in enumerate(calls)
                        ]
                    )
                ]
                if calls
                else []
            )
            script.append(
                LLMResponse(
                    content="Scripted source explanation: 100 AGNT and 60 seconds. No transaction has been sent."
                    if case["category"] == "faq"
                    else "Scripted fixture response; review required for proposals."
                )
            )
        self.inner = FakeLLMProvider(script)

    async def chat(self, *args, **kwargs):
        started = time.perf_counter()
        try:
            if self.preview_path:
                from agent.llm.gemini import _convert_messages, _function_schema

                messages = kwargs["messages"]
                declarations = [
                    {**tool, "parameters": _function_schema(tool["parameters"])}
                    for tool in kwargs.get("tools") or []
                ]
                payload = {
                    "case_id": self.preview_case,
                    "model": self.model,
                    "contents": _convert_messages(messages),
                    "config": {
                        "system_instruction": "\n\n".join(
                            row["content"] for row in messages if row.get("role") == "system"
                        ),
                        "tools": [{"function_declarations": declarations}],
                        "temperature": 0,
                        "max_output_tokens": 512,
                    },
                }
                with self.preview_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
            if self.live_budget and self.inner.call_count < self.inner._max_calls:
                self.live_budget.reserve(self.budget_phase)
            return await self.inner.chat(*args, **kwargs)
        finally:
            self.timings.append((time.perf_counter() - started) * 1000)

    async def aclose(self):
        if hasattr(self.inner, "aclose"):
            await self.inner.aclose()
