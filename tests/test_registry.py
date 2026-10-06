"""Tests for the tool registry, schema generation, and BaseTool mechanics."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from tools.base import BaseTool, RiskLevel, ToolResult
from tools.registry import _REGISTRY, ToolRegistry, clear_registry, register_tool

# Names used by dummy tools (must match enabled_override in tests)
_DUMMY_NAMES = ["dummy_read", "dummy_write"]


# ── Dummy tools for testing ──────────────────────────────────────────


class DummyInput(BaseModel):
    address: str
    amount: float = 0.0


class DummyReadTool(BaseTool):
    name = "dummy_read"
    description = "A dummy READ tool for testing."
    risk_level = RiskLevel.READ
    args_schema = DummyInput

    async def run(self, validated: DummyInput) -> ToolResult:
        return ToolResult.success({"address": validated.address})


class DummyWriteInput(BaseModel):
    to: str
    value: float


class DummyWriteTool(BaseTool):
    name = "dummy_write"
    description = "A dummy WRITE tool for testing."
    risk_level = RiskLevel.WRITE
    args_schema = DummyWriteInput

    async def run(self, validated: DummyWriteInput) -> ToolResult:
        return ToolResult.success({"to": validated.to, "value": validated.value})


# ── Helpers ───────────────────────────────────────────────────────────


def _register_dummy_tools():
    """Register both dummy tools into the global registry."""
    _REGISTRY["dummy_read"] = DummyReadTool()
    _REGISTRY["dummy_write"] = DummyWriteTool()


def _make_registry() -> ToolRegistry:
    """Create a ToolRegistry with dummy tools enabled (bypasses tools.yaml)."""
    return ToolRegistry(enabled_override=_DUMMY_NAMES)


# ── Registration tests ───────────────────────────────────────────────


class TestRegistration:
    def setup_method(self):
        clear_registry()
        _register_dummy_tools()

    def test_register_tool_decorator(self):
        """@register_tool should make the tool findable in the registry."""
        clear_registry()

        @register_tool
        class _InlineTool(BaseTool):
            name = "inline_test"
            description = "inline"
            risk_level = RiskLevel.READ
            args_schema = DummyInput

            async def run(self, validated):
                return ToolResult.success(None)

        registry = ToolRegistry(enabled_override=["inline_test"])
        assert registry.registered_count() == 1
        assert registry.get("inline_test") is not None

    def test_get_tool_by_name(self):
        registry = _make_registry()
        tool = registry.get("dummy_read")
        assert tool is not None
        assert tool.name == "dummy_read"
        assert tool.risk_level == RiskLevel.READ

    def test_get_nonexistent_tool(self):
        registry = _make_registry()
        assert registry.get("nonexistent_tool") is None

    def test_all_tools_returns_enabled(self):
        registry = _make_registry()
        tools = registry.all_tools()
        assert "dummy_read" in tools
        assert "dummy_write" in tools

    def test_list_names_sorted(self):
        registry = _make_registry()
        names = registry.list_names()
        assert names == sorted(names)

    def test_registered_count(self):
        registry = _make_registry()
        assert registry.registered_count() == 2

    def test_disabled_tool_not_returned(self):
        """A registered tool not in the enabled list should not be accessible."""
        registry = ToolRegistry(enabled_override=["dummy_read"])  # only read
        assert registry.get("dummy_write") is None
        assert "dummy_write" not in registry.all_tools()


# ── Schema generation tests ──────────────────────────────────────────


class TestSchemaGeneration:
    def setup_method(self):
        clear_registry()
        _register_dummy_tools()
        self.registry = _make_registry()
        self.read_tool = self.registry.get("dummy_read")
        self.write_tool = self.registry.get("dummy_write")

    def test_input_json_schema(self):
        schema = self.read_tool.get_input_json_schema()
        assert schema["type"] == "object"
        assert "address" in schema["properties"]
        # 'title' should be stripped
        assert "title" not in schema

    def test_openai_tool_format(self):
        tool_def = self.read_tool.to_openai_tool()
        assert tool_def["type"] == "function"
        assert tool_def["function"]["name"] == "dummy_read"
        assert "parameters" in tool_def["function"]
        assert "description" in tool_def["function"]

    def test_anthropic_tool_format(self):
        tool_def = self.read_tool.to_anthropic_tool()
        assert tool_def["name"] == "dummy_read"
        assert "input_schema" in tool_def
        assert tool_def["input_schema"]["type"] == "object"

    def test_gemini_tool_format(self):
        tool_def = self.read_tool.to_gemini_tool()
        assert tool_def["name"] == "dummy_read"
        assert "parameters" in tool_def
        assert tool_def["parameters"]["type"] == "object"
        # Gemini should NOT have $defs
        assert "$defs" not in tool_def["parameters"]

    def test_registry_openai_export(self):
        tools = self.registry.to_openai_tools()
        assert len(tools) == 2
        names = {t["function"]["name"] for t in tools}
        assert names == {"dummy_read", "dummy_write"}

    def test_registry_anthropic_export(self):
        tools = self.registry.to_anthropic_tools()
        assert len(tools) == 2

    def test_registry_gemini_export(self):
        tools = self.registry.to_gemini_tools()
        assert len(tools) == 2


# ── Validation tests ─────────────────────────────────────────────────


class TestValidation:
    def setup_method(self):
        clear_registry()
        _register_dummy_tools()
        self.registry = _make_registry()
        self.tool = self.registry.get("dummy_read")

    def test_valid_args(self):
        validated = self.tool.validate_args({"address": "0xabc"})
        assert validated.address == "0xabc"
        assert validated.amount == 0.0  # default

    def test_invalid_args_raises(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            self.tool.validate_args({})  # missing required 'address'

    def test_extra_fields_ignored_or_rejected(self):
        # Pydantic v2 default: extra fields are ignored
        validated = self.tool.validate_args({"address": "0x1", "unknown": "x"})
        assert validated.address == "0x1"


# ── ToolResult tests ─────────────────────────────────────────────────


class TestToolResult:
    def test_success(self):
        r = ToolResult.success({"balance": 100}, source="mock")
        assert r.ok is True
        assert r.data == {"balance": 100}
        assert r.error is None
        assert r.meta == {"source": "mock"}

    def test_failure(self):
        r = ToolResult.failure("something went wrong", code="INVALID_ADDRESS")
        assert r.ok is False
        assert r.data is None
        assert r.error == "something went wrong"
        assert r.meta == {"code": "INVALID_ADDRESS"}

    def test_serializable(self):
        r = ToolResult.success(42)
        d = r.model_dump()
        assert d["ok"] is True
        assert d["data"] == 42


# ── BaseTool repr ─────────────────────────────────────────────────────


class TestBaseToolRepr:
    def test_repr(self):
        clear_registry()
        _register_dummy_tools()
        registry = _make_registry()
        tool = registry.get("dummy_read")
        assert "dummy_read" in repr(tool)
        assert "READ" in repr(tool)
