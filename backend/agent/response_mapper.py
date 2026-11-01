"""Map public agent events to API responses without exposing thought events."""

from __future__ import annotations

import re
import time
from typing import Any

from backend.agent.language import (
    get_localized_message,
    is_conversational_query,
    resolve_language,
)
from backend.agent.models import AgentResponse, TimelineStep


def map_agent_response(
    *,
    events: list[Any],
    query: str,
    rag: Any,
    request_context: dict[str, Any],
    timeline: list[TimelineStep],
    start: float,
    language: str = "auto",
) -> AgentResponse:
    lang = resolve_language(language, query)
    reply = get_localized_message("NO_FINAL_RESPONSE", lang)
    selected = None
    tool_result = None
    balance_results = {}
    price_result = None
    error = None
    has_final_llm_reply = False
    safe_status = None

    for event in events:
        event_type = getattr(event, "type", None) or (event.get("type") if isinstance(event, dict) else None)
        event_data = getattr(event, "data", None) or (event.get("data") if isinstance(event, dict) else {})

        if event_type == "tool_call":
            selected = event_data.get("name")
            timeline.append(
                TimelineStep(
                    step_number=3,
                    name="Tool selected",
                    status="SUCCESS",
                    tool_name=selected,
                    sanitized_parameters=event_data.get("arguments"),
                )
            )
        elif event_type == "tool_result":
            row = event_data.get("result", {})
            ok = row.get("ok", False)
            if not ok:
                error = "READ_TOOL_FAILED_OR_DISABLED"
            tool_result = row.get("data")
            name = event_data.get("name")

            if ok and name == "get_token_price" and isinstance(tool_result, dict):
                price_result = tool_result

            if (
                ok
                and name in {"get_native_balance", "get_erc20_balance"}
                and isinstance(tool_result, dict)
            ):
                address = tool_result.get("wallet_address") or tool_result.get("address")
                key = (name, address, tool_result.get("token_address"))
                balance_results[key] = tool_result

            step_name = (
                "Proposal tool result"
                if name in {"transfer_eth", "transfer_erc20", "faucet_claim"}
                else "READ tool result"
            )
            timeline.append(
                TimelineStep(
                    step_number=7,
                    name=step_name,
                    status="SUCCESS" if ok else "FAILED",
                    tool_name=name,
                    result=row,
                    duration_ms=event_data.get("duration_ms"),
                )
            )
        elif event_type == "final":
            reply = event_data.get("content", "")
            has_final_llm_reply = bool(reply and reply.strip())
        elif event_type == "error":
            error = "LLM_ERROR"
            diagnostic = event_data.get("diagnostic", {})
            diagnostic = diagnostic if isinstance(diagnostic, dict) else {}
            code = diagnostic.get("http_status")
            safe_status = code if isinstance(code, int) else None
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

    if error:
        if error == "LLM_ERROR":
            err_key = (
                f"LLM_ERROR_{safe_status}"
                if safe_status in {400, 401, 403, 404, 429}
                else "LLM_ERROR_DEFAULT"
            )
            reply = get_localized_message(err_key, lang)
        else:
            reply = get_localized_message("AGENT_INCOMPLETE", lang)

    elif balance_results:
        # Render authoritative RPC amounts instead of accepting digits rewritten by the LLM.
        summaries = []
        for (name, address, _), balance in balance_results.items():
            symbol = balance.get("symbol", "ETH" if name == "get_native_balance" else "TOKEN")
            summaries.append(
                get_localized_message(
                    "BALANCE_SUMMARY",
                    lang,
                    address=address,
                    balance=balance.get("balance", "0"),
                    symbol=symbol,
                    raw_balance=balance.get("raw_balance", "0"),
                )
            )
        canonical = "\n\n".join(summaries)
        reply = (
            reply + "\n\n" + canonical
            if re.search(r"\b(?:chuyển|gửi|transfer|send)\b", query, re.I)
            else canonical
        )

    elif price_result and selected == "get_token_price":
        # Ensure chart marker is present if LLM omitted it for ETH
        marker = price_result.get("chart_marker")
        sym = price_result.get("symbol", "ETH")
        if sym == "ETH" and marker and marker not in reply:
            reply = (reply.strip() + f"\n\n{marker}").strip()

    elif selected is None and not (rag and getattr(rag, "documents", None)):
        # For purely conversational queries (greetings, identity, pleasantries),
        # keep the natural conversational reply.
        # For non-conversational documentation lookups with no matches,
        # never echo raw reference headers or invent documentation answers.
        if not is_conversational_query(query):
            reply = get_localized_message("DOC_NOT_FOUND", lang)
        elif not has_final_llm_reply:
            reply = get_localized_message("GREETING_DEFAULT", lang)

    # Policy guardrail handling
    guardrail = (
        request_context.get("proposal_results")[-1]
        if request_context.get("proposal_results")
        else None
    )
    if guardrail is not None:
        if guardrail.requires_approval:
            reply = get_localized_message("PROPOSAL_READY", lang)
        else:
            reply = get_localized_message(
                "REQUEST_BLOCKED", lang, violations="; ".join(guardrail.violations)
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

    intent = (
        "llm_write_proposal"
        if guardrail is not None
        else "llm_price"
        if selected == "get_token_price"
        else "llm_read"
        if selected
        else "llm_faq"
        if (rag and getattr(rag, "documents", None))
        else "llm_chat"
    )

    return AgentResponse(
        query=query,
        reply=reply,
        intent=intent,
        tool_selected=selected,
        timeline=timeline,
        rag_result=rag,
        blockchain_result=tool_result,
        error=error,
        guardrail_result=guardrail,
        requires_approval=bool(guardrail and guardrail.requires_approval),
        approval_id=guardrail.pending_approval.approval_id
        if guardrail and getattr(guardrail, "pending_approval", None)
        else None,
    )
