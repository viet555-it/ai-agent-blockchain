"""Map public agent events to API responses without exposing thought events."""

import re
import time

from backend.agent.models import AgentResponse, TimelineStep


def map_agent_response(*, events, query, rag, request_context, timeline, start) -> AgentResponse:
    reply = "Không có phản hồi cuối cùng từ Agent."
    selected = None
    tool_result = None
    balance_results = {}
    error = None
    for event in events:
        if event.type == "tool_call":
            selected = event.data["name"]
            timeline.append(
                TimelineStep(
                    step_number=3,
                    name="Tool selected",
                    status="SUCCESS",
                    tool_name=selected,
                    sanitized_parameters=event.data["arguments"],
                )
            )
        elif event.type == "tool_result":
            row = event.data["result"]
            ok = row.get("ok", False)
            if not ok:
                error = "READ_TOOL_FAILED_OR_DISABLED"
            tool_result = row.get("data")
            name = event.data["name"]
            if (
                ok
                and name in {"get_native_balance", "get_erc20_balance"}
                and isinstance(tool_result, dict)
            ):
                address = tool_result.get("wallet_address") or tool_result.get("address")
                key = (name, address, tool_result.get("token_address"))
                balance_results[key] = tool_result
            timeline.append(
                TimelineStep(
                    step_number=7,
                    name="Proposal tool result"
                    if name in {"transfer_eth", "transfer_erc20", "faucet_claim"}
                    else "READ tool result",
                    status="SUCCESS" if ok else "FAILED",
                    tool_name=event.data["name"],
                    result=row,
                    duration_ms=event.data.get("duration_ms"),
                )
            )
        elif event.type == "final":
            reply = event.data["content"]
        elif event.type == "error":
            error = "LLM_ERROR"
            diagnostic = event.data.get("diagnostic")
            diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
            code = diagnostic.get("http_status")
            safe_status = code if type(code) is int else None
            timeline.append(
                TimelineStep(
                    step_number=8,
                    name="LLM provider request",
                    status="FAILED",
                    result={
                        "error": "LLM_ERROR",
                        "http_status": safe_status,
                        "reason": diagnostic.get("reason"),
                    },
                )
            )
        # Do not return or persist provider thought events in the API timeline.
    if error:
        reply = "Agent chưa hoàn thành thao tác. Hãy kiểm tra lỗi và các công cụ đang được bật."
        if error == "LLM_ERROR":
            reasons = {
                400: "Gemini từ chối nội dung hoặc cấu trúc request (HTTP 400). Cần kiểm tra log API.",
                401: "API key không được chấp nhận (HTTP 401). Hãy kiểm tra cấu hình provider.",
                403: "API key hoặc project chưa có quyền gọi model (HTTP 403).",
                404: "Không tìm thấy model đã cấu hình hoặc endpoint tương ứng (HTTP 404).",
                429: "Gemini đang giới hạn quota/tốc độ (HTTP 429). Hãy kiểm tra quota trước khi thử lại.",
            }
            reply = reasons.get(
                safe_status,
                "Lời gọi model thất bại. Xem lỗi ‘LLM call failed’ trong terminal chạy API; chưa có giao dịch nào được gửi bởi lời gọi này.",
            )
    elif balance_results:
        # Render authoritative RPC amounts instead of accepting digits rewritten by the LLM.
        summaries = []
        for (name, address, _), balance in balance_results.items():
            symbol = balance.get("symbol", "ETH" if name == "get_native_balance" else "TOKEN")
            summaries.append(
                f"Số dư của ví `{address}`: **{balance['balance']} {symbol}**.\n"
                f"Raw balance: `{balance['raw_balance']}`."
            )
        canonical = "\n\n".join(summaries)
        # A READ used during transfer planning must not erase a question
        # asking the user to supply a missing parameter.
        reply = (
            reply + "\n\n" + canonical
            if re.search(r"\b(?:chuyển|gửi|transfer|send)\b", query, re.I)
            else canonical
        )
    elif selected is None and not rag.documents:
        # Never echo raw reference headers or invent a documentation answer.
        reply = "Chưa tìm thấy tài liệu phù hợp để trả lời câu hỏi này. Bạn hãy nêu rõ chức năng hoặc tên hàm cần tra cứu."
    guardrail = (
        request_context["proposal_results"][-1] if request_context["proposal_results"] else None
    )
    if guardrail is not None:
        reply = (
            "Giao dịch đã được chuẩn bị. Hãy kiểm tra và duyệt trong cửa sổ xác nhận; chưa có giao dịch nào được gửi."
            if guardrail.requires_approval
            else "Yêu cầu bị chặn: " + "; ".join(guardrail.violations)
        )
        timeline.append(
            TimelineStep(
                step_number=5,
                name="Transaction policy and simulation",
                status="PENDING_APPROVAL" if guardrail.requires_approval else "BLOCKED",
                result=guardrail.model_dump(),
            )
        )
    timeline.append(
        TimelineStep(
            step_number=9,
            name="Final Agent response",
            status=(
                "PENDING_APPROVAL"
                if guardrail and guardrail.requires_approval
                else "BLOCKED"
                if guardrail and not guardrail.is_allowed
                else "FAILED"
                if error
                else "SUCCESS"
            ),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )
    )
    return AgentResponse(
        query=query,
        reply=reply,
        intent="llm_write_proposal"
        if guardrail is not None
        else "llm_read"
        if selected
        else "llm_faq",
        tool_selected=selected,
        timeline=timeline,
        rag_result=rag,
        blockchain_result=tool_result,
        error=error,
        guardrail_result=guardrail,
        requires_approval=bool(guardrail and guardrail.requires_approval),
        approval_id=guardrail.pending_approval.approval_id
        if guardrail and guardrail.pending_approval
        else None,
    )
