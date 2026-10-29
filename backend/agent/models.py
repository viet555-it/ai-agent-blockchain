"""Public agent response and timeline contracts shared by runtimes."""

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.guardrail.models import GuardrailResult
from backend.rag.rag_adapter import RAGSearchResult


class TimelineStep(BaseModel):
    """Step in the 9-stage Agent workflow timeline."""

    step_number: int
    name: str
    status: str  # SUCCESS, PENDING_APPROVAL, BLOCKED, FAILED, INFO
    timestamp: float = Field(default_factory=time.time)
    duration_ms: float | None = None
    tool_name: str | None = None
    sanitized_parameters: dict[str, Any] | None = None
    result: Any | None = None
    error: str | None = None


class AgentResponse(BaseModel):
    """Standardized response from the AI Agent."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    query: str
    reply: str
    intent: str
    tool_selected: str | None = None
    timeline: list[TimelineStep] = Field(default_factory=list)
    guardrail_result: GuardrailResult | None = None
    rag_result: RAGSearchResult | None = None
    requires_approval: bool = False
    approval_id: str | None = None
    blockchain_result: dict[str, Any] | None = None
    error: str | None = None
