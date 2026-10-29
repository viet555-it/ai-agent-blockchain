"""Construct an LLM provider from explicit settings without eager SDK loading."""

from typing import Any

from config.settings import LLMProviderName, Settings


def create_llm(settings: Settings) -> Any:
    """Create the appropriate LLMProvider based on settings."""
    match settings.llm_provider:
        case LLMProviderName.GEMINI:
            from agent.llm.gemini import GeminiProvider

            if not settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
            return GeminiProvider(api_key=settings.gemini_api_key, model=settings.llm_model)

        case LLMProviderName.ANTHROPIC:
            from agent.llm.anthropic import AnthropicProvider

            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
            return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.llm_model)

        case LLMProviderName.OPENAI:
            from agent.llm.openai_adapter import OpenAIProvider

            if not settings.openai_api_key:
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            return OpenAIProvider(api_key=settings.openai_api_key, model=settings.llm_model)

        case LLMProviderName.FAKE:
            from agent.llm.fake import FakeLLMProvider

            return FakeLLMProvider()

        case _:
            raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")
