"""Tool registry with auto-discovery and ``@register_tool`` decorator.

Adding a new tool requires only:
1. Create a file in ``tools/read/`` or ``tools/write/``.
2. Subclass ``BaseTool`` and decorate with ``@register_tool``.
3. (Optional) enable/disable in ``config/tools.yaml``.

The registry auto-discovers tools by importing all modules in ``tools/read/``
and ``tools/write/``.  Schema generation adapts to each LLM provider format.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import Any

from config.settings import load_tools_config
from tools.base import BaseTool

logger = logging.getLogger(__name__)

# ── Global registry ──────────────────────────────────────────────────

_REGISTRY: dict[str, BaseTool] = {}


def register_tool(cls: type[BaseTool]) -> type[BaseTool]:
    """Class decorator – registers a ``BaseTool`` subclass in the global registry.

    Usage::

        @register_tool
        class GetNativeBalance(BaseTool):
            name = "get_native_balance"
            ...
    """
    instance = cls()
    if instance.name in _REGISTRY:
        logger.warning("Tool %r registered twice – overwriting", instance.name)
    _REGISTRY[instance.name] = instance
    logger.debug("Registered tool: %s [%s]", instance.name, instance.risk_level)
    return cls


class ToolRegistry:
    """Manages tool lifecycle: discovery, filtering, and schema export.

    Args:
        enabled_override: If provided, overrides ``tools.yaml`` for deciding
            which tools are enabled. Pass ``None`` (default) to read from config.
            Useful for testing.
    """

    def __init__(self, enabled_override: list[str] | None = None) -> None:
        self._discovered = False
        self._enabled_override = enabled_override

    # ── Discovery ─────────────────────────────────────────────────────

    def discover(self) -> None:
        """Import all modules in ``tools/read/`` and ``tools/write/`` to trigger
        ``@register_tool`` decorators.  Safe to call multiple times.
        """
        if self._discovered:
            return

        for package_name in ("tools.read", "tools.write"):
            try:
                package = importlib.import_module(package_name)
            except ImportError:
                logger.debug("Package %s not found – skipping", package_name)
                continue

            for _importer, module_name, _is_pkg in pkgutil.iter_modules(
                package.__path__, prefix=f"{package_name}."
            ):
                try:
                    importlib.import_module(module_name)
                except Exception:
                    logger.exception("Failed to import tool module %s", module_name)

        self._discovered = True
        logger.info("Tool discovery complete: %d tools found", len(_REGISTRY))

    # ── Access ────────────────────────────────────────────────────────

    def get(self, name: str) -> BaseTool | None:
        """Look up a tool by name, respecting enabled list."""
        tool = _REGISTRY.get(name)
        if tool is None:
            return None
        if not self._is_enabled(name):
            logger.debug("Tool %s is disabled in config", name)
            return None
        return tool

    def all_tools(self) -> dict[str, BaseTool]:
        """Return all enabled tools."""
        return {
            name: tool
            for name, tool in _REGISTRY.items()
            if self._is_enabled(name)
        }

    def list_names(self) -> list[str]:
        """Return sorted list of enabled tool names."""
        return sorted(self.all_tools().keys())

    # ── Schema export ─────────────────────────────────────────────────

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Export all enabled tools as OpenAI function-calling definitions."""
        return [tool.to_openai_tool() for tool in self.all_tools().values()]

    def to_anthropic_tools(self) -> list[dict[str, Any]]:
        """Export all enabled tools as Anthropic tool definitions."""
        return [tool.to_anthropic_tool() for tool in self.all_tools().values()]

    def to_gemini_tools(self) -> list[dict[str, Any]]:
        """Export all enabled tools as Gemini function declarations."""
        return [tool.to_gemini_tool() for tool in self.all_tools().values()]

    # ── Internal ──────────────────────────────────────────────────────

    def _is_enabled(self, name: str) -> bool:
        """Check whether a tool is enabled.

        Priority:
        1. ``enabled_override`` passed at construction time (for tests).
        2. ``config/tools.yaml`` ``enabled`` list.
        3. No config at all → all registered tools are enabled.
        """
        if self._enabled_override is not None:
            return name in self._enabled_override

        config = load_tools_config()
        enabled_list = config.get("enabled")
        if enabled_list is None:
            # No config → all registered tools are enabled
            return True
        return name in enabled_list

    # ── Debugging ─────────────────────────────────────────────────────

    @staticmethod
    def registered_count() -> int:
        """Total number of registered tools (ignoring enabled/disabled)."""
        return len(_REGISTRY)

    def __repr__(self) -> str:
        enabled = self.list_names()
        return f"ToolRegistry(enabled={enabled})"


def get_registry() -> ToolRegistry:
    """Create a registry and run auto-discovery."""
    registry = ToolRegistry()
    registry.discover()
    return registry


def clear_registry() -> None:
    """Clear the global registry (for testing)."""
    _REGISTRY.clear()
