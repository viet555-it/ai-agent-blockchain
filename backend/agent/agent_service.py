"""AI Agent Service for Blockchain Tools.

Orchestrates intent parsing, RAG context retrieval, tool selection, parameter validation,
guardrail policy evaluation, human approval workflow, and execution timeline generation.
"""

import logging
import time
import uuid
from typing import Any

from backend.agent.legacy import intent as intent_rules
from backend.agent.legacy import reads, replies, validation
from backend.agent.models import AgentResponse as AgentResponse
from backend.agent.models import TimelineStep as TimelineStep
from backend.guardrail.policy_engine import PolicyEngine
from backend.rag.rag_adapter import RAGAdapter, RAGSearchResult
from backend.services.blockchain_service import BlockchainService

logger = logging.getLogger("agent.service")


class BlockchainAgent:
    """Agent runtime integrating BlockchainService, PolicyEngine, and RAGAdapter."""

    def __init__(
        self,
        blockchain_service: BlockchainService,
        policy_engine: PolicyEngine,
        rag_adapter: RAGAdapter | None = None,
        default_wallet: str | None = None,
    ):
        self.blockchain = blockchain_service
        self.policy = policy_engine
        self.rag = rag_adapter or RAGAdapter()
        # Fallback to deployer address if no active wallet is passed
        self.default_wallet = default_wallet or "0xeF9F53B00B069782256fC20697E7cf6a3136F9BC"

    def process_message(self, query: str, user_wallet: str | None = None) -> AgentResponse:
        """Process natural-language prompt and execute full 9-step workflow."""
        start_time = time.perf_counter()
        request_id = f"req-{uuid.uuid4().hex[:8]}"
        timeline: list[TimelineStep] = []
        active_wallet = user_wallet or self.default_wallet

        # ── Step 1: Request received ──────────────────────────────────────────
        t0 = time.perf_counter()
        timeline.append(
            TimelineStep(
                step_number=1,
                name="Request received",
                status="SUCCESS",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                result={"query": query, "request_id": request_id, "active_wallet": active_wallet},
            )
        )

        # ── Step 2: Intent analyzed ───────────────────────────────────────────
        t0 = time.perf_counter()
        intent, extracted_params = self._analyze_intent(query, active_wallet)
        rag_result = self.rag.retrieve(query)
        timeline.append(
            TimelineStep(
                step_number=2,
                name="Intent analyzed",
                status="SUCCESS",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                result={
                    "intent": intent,
                    "extracted_parameters": extracted_params,
                    "has_rag_context": rag_result.has_relevant_context,
                },
            )
        )

        # ── Step 3: Tool selected ─────────────────────────────────────────────
        t0 = time.perf_counter()
        tool_name = self._select_tool(intent)
        timeline.append(
            TimelineStep(
                step_number=3,
                name="Tool selected",
                status="SUCCESS",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                tool_name=tool_name,
                result={"tool_name": tool_name},
            )
        )

        # If it's a pure conversation / FAQ without tool call:
        if tool_name == "none":
            reply = self._generate_faq_reply(query, rag_result)
            timeline.append(
                TimelineStep(
                    step_number=9,
                    name="Final Agent response",
                    status="SUCCESS",
                    duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                    result={"reply": reply},
                )
            )
            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=None,
                timeline=timeline,
                rag_result=rag_result,
            )

        # ── Step 4: Parameters validated ──────────────────────────────────────
        t0 = time.perf_counter()
        val_ok, val_err, clean_params = self._validate_parameters(tool_name, extracted_params)
        timeline.append(
            TimelineStep(
                step_number=4,
                name="Parameters validated",
                status="SUCCESS" if val_ok else "FAILED",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                tool_name=tool_name,
                sanitized_parameters=clean_params,
                error=val_err,
            )
        )

        if not val_ok:
            reply = f"Parameter validation failed: {val_err}"
            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=tool_name,
                timeline=timeline,
                error=val_err,
            )

        # ── Step 5: Guardrail evaluation ──────────────────────────────────────
        t0 = time.perf_counter()
        # If write operation, optionally perform dry-run simulation first
        sim_data = None
        if tool_name in ("erc20_transfer", "native_transfer"):
            try:
                sim_data = self.blockchain.simulate_transfer(
                    sender=active_wallet,
                    recipient=clean_params["recipient"],
                    amount_token=clean_params["amount"],
                    token_address=clean_params.get("token_address"),
                )
            except Exception as e:
                sim_data = {"isValid": False, "reason": f"Simulation check error: {str(e)}"}

        guardrail_res = self.policy.evaluate_request(
            operation=tool_name,
            parameters=clean_params,
            simulation_data=sim_data,
        )

        step_status = "SUCCESS"
        if not guardrail_res.is_allowed:
            step_status = "BLOCKED"
        elif guardrail_res.requires_approval:
            step_status = "PENDING_APPROVAL"

        timeline.append(
            TimelineStep(
                step_number=5,
                name="Guardrail evaluation",
                status=step_status,
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                tool_name=tool_name,
                result={
                    "is_allowed": guardrail_res.is_allowed,
                    "operation_type": guardrail_res.operation_type,
                    "violations": guardrail_res.violations,
                    "warnings": guardrail_res.warnings,
                    "simulation": sim_data,
                },
            )
        )

        if not guardrail_res.is_allowed:
            violations_str = "; ".join(guardrail_res.violations)
            reply = f"Operation rejected by Guardrail Policy Engine: {violations_str}"
            timeline.append(
                TimelineStep(
                    step_number=9,
                    name="Final Agent response",
                    status="BLOCKED",
                    duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                    result={"reply": reply},
                )
            )
            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=tool_name,
                timeline=timeline,
                guardrail_result=guardrail_res,
                rag_result=rag_result,
            )

        # ── Step 6: User approval required, if applicable ─────────────────────
        if guardrail_res.requires_approval:
            t0 = time.perf_counter()
            approval = guardrail_res.pending_approval
            timeline.append(
                TimelineStep(
                    step_number=6,
                    name="User approval required",
                    status="PENDING_APPROVAL",
                    duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                    tool_name=tool_name,
                    result={
                        "approval_id": approval.approval_id,
                        "description": approval.description,
                        "expires_at": approval.expires_at,
                        "parameters": approval.parameters,
                        "simulation": sim_data,
                    },
                )
            )

            reply = (
                f"I have prepared the transaction ({approval.description}). "
                f"Because this is a state-changing write operation, explicit human approval is required. "
                f"Please review the details in the approval panel to approve or reject."
            )
            timeline.append(
                TimelineStep(
                    step_number=9,
                    name="Final Agent response",
                    status="PENDING_APPROVAL",
                    duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                    result={"reply": reply},
                )
            )

            return AgentResponse(
                request_id=request_id,
                query=query,
                reply=reply,
                intent=intent,
                tool_selected=tool_name,
                timeline=timeline,
                guardrail_result=guardrail_res,
                rag_result=rag_result,
                requires_approval=True,
                approval_id=approval.approval_id,
            )

        # ── Step 7: Tool executed (for Read-only operations) ──────────────────
        t0 = time.perf_counter()
        tool_res, exec_err = self._execute_read_tool(tool_name, clean_params)
        timeline.append(
            TimelineStep(
                step_number=7,
                name="Tool executed",
                status="SUCCESS" if exec_err is None else "FAILED",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                tool_name=tool_name,
                result=tool_res,
                error=exec_err,
            )
        )

        # ── Step 8: Blockchain result received ────────────────────────────────
        t0 = time.perf_counter()
        timeline.append(
            TimelineStep(
                step_number=8,
                name="Blockchain result received",
                status="SUCCESS" if exec_err is None else "FAILED",
                duration_ms=round((time.perf_counter() - t0) * 1000, 2),
                result=tool_res or {"error": exec_err},
            )
        )

        # ── Step 9: Final Agent response ──────────────────────────────────────
        t0 = time.perf_counter()
        reply = self._format_read_reply(tool_name, tool_res, exec_err, rag_result)
        timeline.append(
            TimelineStep(
                step_number=9,
                name="Final Agent response",
                status="SUCCESS" if exec_err is None else "FAILED",
                duration_ms=round((time.perf_counter() - start_time) * 1000, 2),
                result={"reply": reply},
            )
        )

        return AgentResponse(
            request_id=request_id,
            query=query,
            reply=reply,
            intent=intent,
            tool_selected=tool_name,
            timeline=timeline,
            guardrail_result=guardrail_res,
            rag_result=rag_result,
            blockchain_result=tool_res,
            error=exec_err,
        )

    # ── Intent Analysis & Routing ─────────────────────────────────────────────

    def _analyze_intent(self, query: str, active_wallet: str) -> tuple[str, dict[str, Any]]:
        return intent_rules.analyze_intent(query, active_wallet)

    def _select_tool(self, intent: str) -> str:
        return intent_rules.select_tool(intent)

    def _validate_parameters(
        self, tool_name: str, raw_params: dict[str, Any]
    ) -> tuple[bool, str | None, dict[str, Any]]:
        return validation.validate_parameters(
            self.blockchain, self.default_wallet, tool_name, raw_params
        )

    def _execute_read_tool(
        self, tool_name: str, params: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str | None]:
        return reads.execute_read_tool(self.blockchain, self.default_wallet, tool_name, params)

    def _format_read_reply(
        self,
        tool_name: str,
        result: dict[str, Any] | None,
        error: str | None,
        rag_result: RAGSearchResult,
    ) -> str:
        return replies.format_read_reply(tool_name, result, error, rag_result)

    def _generate_faq_reply(self, query: str, rag_result: RAGSearchResult) -> str:
        return replies.generate_faq_reply(query, rag_result)
