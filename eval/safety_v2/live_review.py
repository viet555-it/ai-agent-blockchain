"""Build an offline payload review and enforce a separate durable request allowance.

This module does not construct a network provider. A future live runner must bind
the reviewed model/token settings and obtain authorization before using the wrapper.
"""

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from backend.agent.read_tools import BackendReadRegistry
from eval.safety_v2.cases import initial_messages
from eval.safety_v2.runner import load_dataset, source_manifest


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def build_review(model, *, request_cap=80):
    if not isinstance(model, str) or not model.strip() or len(model) > 160:
        raise ValueError("An explicit model name is required")
    if type(request_cap) is not int or not 1 <= request_cap <= 160:
        raise ValueError("request_cap must be in 1..160")
    rows, dataset_hash = load_dataset()
    tools = BackendReadRegistry(None, object()).to_gemini_tools()
    review = {
        "protocol": "safety-v2-live-review-1",
        "provider": "gemini",
        "model": model,
        "dataset_sha256": dataset_hash,
        "source_sha256": source_manifest(),
        "limits": {
            "total_requests": request_cap,
            "requests_per_case": 4,
            "max_output_tokens_per_request": 512,
            "max_input_tokens_per_request": 6400,
            "input_token_measurement": "cl100k_base_estimate_including_tool_schemas",
            "temperature": 0,
            "automatic_retries": 0,
        },
        "tools": tools,
        "cases": [{"id": row["id"], "initial_messages": initial_messages(row)} for row in rows],
        "followup_scope": "Same initial system/user input; only model messages and results of listed fixture tools may follow. No additional user turns.",
        "execution_scope": "Temporary SQLite and mock blockchain; no signer, testnet transaction or production RAG. Gold labels and expected decisions are excluded from payload.",
    }
    return {"review_sha256": fingerprint(review), "review": review}


def validate_review(packet):
    review = packet["review"]
    if packet["review_sha256"] != fingerprint(review):
        raise ValueError("Payload review integrity mismatch")
    current = build_review(review["model"], request_cap=review["limits"]["total_requests"])
    if current != packet:
        raise ValueError("Reviewed payload/source changed; prepare a new review")
    return review


def write_review(directory, packet):
    from agent.llm.gemini import _convert_messages, _function_schema

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "review.json").write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    review = packet["review"]
    with (directory / "payload-preview.jsonl").open("w", encoding="utf-8") as stream:
        for row in review["cases"]:
            payload = {
                "case_id": row["id"],
                "model": review["model"],
                "contents": _convert_messages(row["initial_messages"]),
                "config": {
                    "system_instruction": row["initial_messages"][0]["content"],
                    "tools": [
                        {
                            "function_declarations": [
                                {**tool, "parameters": _function_schema(tool["parameters"])}
                                for tool in review["tools"]
                            ]
                        }
                    ],
                    "temperature": 0,
                    "max_output_tokens": 512,
                },
            }
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
    cap = review["limits"]["total_requests"]
    lines = [
        "# Phạm vi đề xuất cho đánh giá LLM thật",
        "",
        f"Model lấy từ cấu hình dự án: `{review['model']}`.",
        "",
        f"Gửi tối đa {cap} request cho 40 ca Việt/Anh; tối đa 4 request/ca, 512 output token/request, tổng trần output {cap * 512} token. Temperature 0, không tự retry. Đây là giới hạn request/token, không phải báo giá hoặc cam kết miễn phí.",
        "",
        "Nội dung gồm system prompt, prompt benchmark, 9 schema công cụ, địa chỉ ví/contract thử nghiệm, policy và trạng thái hạn mức giả lập. Hai ca có tài liệu RAG độc hại được chèn vào retrieval context. Các lượt sau có thể chứa phản hồi model và kết quả fixture tool được liệt kê; không gửi gold/kỳ vọng chấm điểm.",
        "",
        "Không gửi API key, private key, lịch sử ví thật, database cá nhân hoặc RPC URL chứa key trong payload. API key chỉ được dùng làm credential khi có live runner được cấp quyền. Không ký hoặc gửi giao dịch; phần blockchain dùng mock.",
        "",
        "Bản này chỉ là xem trước cục bộ. Chưa gọi provider, chưa tạo ledger ngân sách và chưa có kết quả live. Ngân sách G3.5 không được tái sử dụng.",
        "",
        f"Review hash: `{packet['review_sha256']}`.",
        "",
    ]
    (directory / "review.md").write_text("\n".join(lines), encoding="utf-8")


class LiveRequestLedger:
    """Reserve before a provider call; failures still consume the reviewed cap."""

    def __init__(self, path, packet):
        self.path = Path(path)
        self.packet = packet
        self.review = validate_review(packet)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock", timeout=5)

    def snapshot(self):
        if not self.path.exists():
            return {
                "review_sha256": self.packet["review_sha256"],
                "limits": self.review["limits"],
                "reservations": [],
            }
        state = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            state.get("review_sha256") != self.packet["review_sha256"]
            or state.get("limits") != self.review["limits"]
        ):
            raise ValueError("Review/ledger mismatch; do not reset the ledger")
        records = state.get("reservations")
        ids = {row["id"] for row in self.review["cases"]}
        if not isinstance(records, list) or any(
            row.get("case_id") not in ids or row.get("ordinal") != i + 1
            for i, row in enumerate(records)
        ):
            raise ValueError("Malformed request reservations")
        return state

    def reserve(self, case_id):
        if case_id not in {row["id"] for row in self.review["cases"]}:
            raise ValueError("Unreviewed case")
        with self.lock:
            state = self.snapshot()
            records, limits = state["reservations"], self.review["limits"]
            if (
                len(records) >= limits["total_requests"]
                or sum(row["case_id"] == case_id for row in records) >= limits["requests_per_case"]
            ):
                raise RuntimeError("Safety v2 reviewed request cap reached")
            records.append(
                {
                    "case_id": case_id,
                    "ordinal": len(records) + 1,
                    "reserved_at_utc": datetime.now(UTC).isoformat(),
                }
            )
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent, delete=False
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump(state, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()


class ReviewedProvider:
    """Provider-independent guard used with test doubles until live execution is authorized."""

    def __init__(self, inner, ledger, case_id, counter):
        self.inner, self.ledger, self.case_id, self.counter = inner, ledger, case_id, counter
        self.review = ledger.review
        if (
            getattr(inner, "_model", None) != self.review["model"]
            or getattr(inner, "_max_output_tokens", None)
            != self.review["limits"]["max_output_tokens_per_request"]
        ):
            raise ValueError("Provider model/output-token settings differ from review")
        self.initial = next(
            row["initial_messages"] for row in self.review["cases"] if row["id"] == case_id
        )

    async def chat(self, messages, tools=None):
        if messages[:2] != self.initial or any(
            row.get("role") not in {"assistant", "tool"} for row in messages[2:]
        ):
            raise ValueError("Messages exceed reviewed input scope")
        if tools != self.review["tools"]:
            raise ValueError("Tool schema changed after payload review")
        if (
            self.counter.count_messages(messages) + self.counter.count(canonical(tools))
            > self.review["limits"]["max_input_tokens_per_request"]
        ):
            raise ValueError("Reviewed input token cap exceeded")
        self.ledger.reserve(self.case_id)
        return await self.inner.chat(messages=messages, tools=tools)

    @property
    def last_error(self):
        return getattr(self.inner, "last_error", None)
