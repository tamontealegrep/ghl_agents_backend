"""Multi-provider LLM support: OpenAI, Anthropic (Claude) and Google (Gemini) with automatic failover.

The runtime only needs the two-method ``LLMClient`` protocol (``complete`` and ``extract_structured``);
``build_llm_client`` returns one that tries the providers named in ``LLM_PROVIDERS`` in order.
"""

from __future__ import annotations

from .config import LLMSettings, load_llm_settings
from .errors import AllProvidersFailedError, ErrorKind, LLMProviderError, NoProviderConfiguredError
from .factory import build_llm_client
from .failover import FailoverLLMClient

__all__ = [
    "AllProvidersFailedError",
    "ErrorKind",
    "FailoverLLMClient",
    "LLMProviderError",
    "LLMSettings",
    "NoProviderConfiguredError",
    "build_llm_client",
    "load_llm_settings",
]
