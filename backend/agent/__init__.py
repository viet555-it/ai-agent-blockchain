"""Agent contracts; the legacy runtime is loaded only when requested."""

from backend.agent.models import AgentResponse, TimelineStep

__all__ = ["BlockchainAgent", "AgentResponse", "TimelineStep"]


def __getattr__(name):
    if name == "BlockchainAgent":
        from backend.agent.agent_service import BlockchainAgent

        return BlockchainAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
