"""Builds the process's LLM client from the environment."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from .config import LLMSettings, ProviderSettings, load_llm_settings
from .failover import FailoverLLMClient
from .providers import AnthropicProvider, GeminiProvider, OpenAIProvider, Provider

__all__ = ["build_llm_client", "build_provider"]

logger = logging.getLogger(__name__)


def build_provider(settings: ProviderSettings, timeout_seconds: float) -> Provider:
    """Creates one provider adapter.

    Args:
        settings: Provider name, key and model.
        timeout_seconds: Request timeout.
    """
    if settings.name == "openai":
        return OpenAIProvider(settings.api_key, settings.model, timeout_seconds)
    if settings.name == "anthropic":
        return AnthropicProvider(settings.api_key, settings.model, timeout_seconds)
    if settings.name == "gemini":
        return GeminiProvider(settings.api_key, settings.model, timeout_seconds)
    raise ValueError(f"Unknown LLM provider {settings.name!r}")


def build_llm_client(
    env: Mapping[str, str] | None = None, *, settings: LLMSettings | None = None
) -> FailoverLLMClient:
    """The runtime's LLM client: every usable provider, in the order ``LLM_PROVIDERS`` gives.

    Args:
        env: Variables to read (the process environment when omitted). Ignored when ``settings`` is given.
        settings: Already loaded settings.

    Returns:
        A client that fails over from one provider to the next.

    Raises:
        NoProviderConfiguredError: No listed provider has an API key.
        ValueError: The configuration is invalid.
    """
    settings = settings or load_llm_settings(env)
    providers = [build_provider(p, settings.timeout_seconds) for p in settings.providers]
    logger.info("LLM providers, by priority: %s", ", ".join(f"{p.name} ({p.model})" for p in providers))
    return FailoverLLMClient(providers, cooldown_seconds=settings.cooldown_seconds)
