"""Base classes for the tool layer.

Every tool extends ``BaseTool`` and declares its *risk level* (READ or WRITE),
a Pydantic v2 input schema, and a ``run()`` method. Results are returned as a
standardised ``ToolResult`` so the agent loop can handle successes and errors
uniformly.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class RiskLevel(StrEnum):
    """Whether a tool only reads data or mutates on-chain state."""

    READ = "READ"
    WRITE = "WRITE"


class ToolResult(BaseModel):
    """Standardised result returned by every tool execution.

    Attributes:
        ok: ``True`` if the tool ran successfully.
        data: Arbitrary payload on success.
        error: Human-readable error message on failure.
        meta: Optional metadata (gas used, block number, latency, …).
    """

    ok: bool
    data: Any = None
    error: str | None = None
    meta: dict[str, Any] | None = None

    @classmethod
    def success(cls, data: Any, **meta: Any) -> ToolResult:
        return cls(ok=True, data=data, meta=meta if meta else None)

    @classmethod
    def failure(cls, error: str, **meta: Any) -> ToolResult:
        return cls(ok=False, error=error, meta=meta if meta else None)


@dataclass
class ToolContext:
    """Runtime context injected into every tool execution.

    Attributes:
        blockchain: A ``BlockchainService`` implementation (Web3 or Mock).
        settings: Application ``Settings`` instance.
    """

    blockchain: Any  # services.blockchain.BlockchainService
    settings: Any  # config.settings.Settings
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict)
    request_context: dict[str, Any] = field(default_factory=dict)

    def cache_get(self, key: str, ttl: float = 60.0) -> Any | None:
        """Return cached value if still valid, else ``None``."""
        if key in self._cache:
            ts, val = self._cache[key]
            if time.time() - ts < ttl:
                return val
            del self._cache[key]
        return None

    def cache_set(self, key: str, value: Any) -> None:
        """Store a value in the cache with current timestamp."""
        self._cache[key] = (time.time(), value)


class BaseTool(abc.ABC):
    """Abstract base class for all agent tools.

    Subclasses must set class-level attributes ``name``, ``description``,
    ``risk_level``, and ``args_schema`` (a Pydantic v2 ``BaseModel``), then
    implement ``run(validated, ctx)``.

    Example::

        class GetNativeBalance(BaseTool):
            name = "get_native_balance"
            description = "Get the native ETH balance of an address on Sepolia."
            risk_level = RiskLevel.READ
            args_schema = GetNativeBalanceInput

            async def run(self, validated: GetNativeBalanceInput, ctx: ToolContext) -> ToolResult:
                ...
    """

    name: str
    description: str
    risk_level: RiskLevel
    args_schema: type[BaseModel]  # Pydantic v2 model for input validation

    @abc.abstractmethod
    async def run(self, validated: BaseModel, ctx: ToolContext) -> ToolResult:
        """Execute the tool with *already-validated* arguments.

        Args:
            validated: Parsed and validated input from the LLM.
            ctx: Runtime context with blockchain service, settings, and cache.

        Must not raise – return ``ToolResult.failure(...)`` instead.
        """

    # ── Schema helpers ────────────────────────────────────────────────

    def get_input_json_schema(self) -> dict[str, Any]:
        """Return JSON Schema dict derived from ``args_schema``."""
        schema = self.args_schema.model_json_schema()
        # Remove pydantic metadata keys that LLM providers don't need
        schema.pop("title", None)
        return schema

    def to_openai_tool(self) -> dict[str, Any]:
        """Format as an OpenAI-compatible function tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_input_json_schema(),
            },
        }

    def to_anthropic_tool(self) -> dict[str, Any]:
        """Format as an Anthropic-compatible tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.get_input_json_schema(),
        }

    def to_gemini_tool(self) -> dict[str, Any]:
        """Format as a Gemini-compatible function declaration.

        Gemini uses ``function_declarations`` inside a ``tools`` wrapper.
        The schema must use ``object`` type at the top level.
        """
        schema = self.get_input_json_schema()
        # Gemini doesn't support $defs / $ref – flatten if needed
        schema.pop("$defs", None)
        return {
            "name": self.name,
            "description": self.description,
            "parameters": schema,
        }

    def validate_args(self, raw_args: dict[str, Any]) -> BaseModel:
        """Parse and validate raw arguments against ``args_schema``.

        Raises ``pydantic.ValidationError`` on invalid input – the caller
        (agent loop) catches this and feeds the error back to the LLM.
        """
        return self.args_schema.model_validate(raw_args)

    def __repr__(self) -> str:
        return f"<Tool {self.name} [{self.risk_level}]>"


class ToolCallRecord(BaseModel):
    """Immutable record of a single tool invocation for audit/logging."""

    tool_name: str
    risk_level: RiskLevel
    arguments: dict[str, Any]
    result: ToolResult
    timestamp: datetime = datetime.now(UTC)
    duration_ms: float | None = None
