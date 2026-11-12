"""LLM provider settings, read from the environment.

Variables:
    LLM_PROVIDERS                  Providers to use, most preferred first, comma separated
                                   (``openai,anthropic,gemini``). One left out of the list is never used.
                                   Default ``openai``.
    OPENAI_API_KEY / OPENAI_MODEL
    ANTHROPIC_API_KEY / ANTHROPIC_MODEL
    GEMINI_API_KEY / GEMINI_MODEL  ``GOOGLE_API_KEY`` is accepted when ``GEMINI_API_KEY`` is empty.
    LLM_TIMEOUT_SECONDS            Per request, per provider (default 60). A hung provider must not hold the
                                   conversation: the call fails over once this runs out.
    LLM_COOLDOWN_SECONDS           How long a provider that ran out of credits or has a bad key is skipped
                                   (default 300). Short outages and rate limits use ``TRANSIENT_COOLDOWN_SECONDS``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from .errors import NoProviderConfiguredError

__all__ = [
    "DEFAULT_MODELS",
    "KEY_VARIABLES",
    "PROVIDER_NAMES",
    "LLMSettings",
    "ProviderSettings",
    "load_llm_settings",
]

logger = logging.getLogger(__name__)

PROVIDER_NAMES = ("openai", "anthropic", "gemini")

KEY_VARIABLES: dict[str, tuple[str, ...]] = {
    "openai": ("OPENAI_API_KEY",),
    "anthropic": ("ANTHROPIC_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
}
MODEL_VARIABLES = {"openai": "OPENAI_MODEL", "anthropic": "ANTHROPIC_MODEL", "gemini": "GEMINI_MODEL"}
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-haiku-5-5",
    "gemini": "gemini-2.5-flash",
}

DEFAULT_PROVIDERS = "openai"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_COOLDOWN_SECONDS = 300.0
TRANSIENT_COOLDOWN_SECONDS = 30.0


@dataclass(frozen=True)
class ProviderSettings:
    """One provider ready to use."""

    name: str
    api_key: str
    model: str


@dataclass(frozen=True)
class LLMSettings:
    """Providers in priority order, plus the failover timings.

    Attributes:
        providers: Usable providers (listed and with a key), most preferred first.
        timeout_seconds: Request timeout for each provider call.
        cooldown_seconds: How long a provider with a bad key or no credits is skipped.
    """

    providers: tuple[ProviderSettings, ...]
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS


def _first_value(env: Mapping[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = (env.get(name) or "").strip()
        if value:
            return value
    return ""


def _seconds(env: Mapping[str, str], name: str, default: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number of seconds, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {raw!r}")
    return value


def parse_provider_list(raw: str) -> list[str]:
    """Splits ``LLM_PROVIDERS`` into provider names, in order, without repeats.

    Raises:
        ValueError: A name is not one of ``PROVIDER_NAMES`` (a typo must not silently drop a provider).
    """
    names: list[str] = []
    for item in raw.split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name not in PROVIDER_NAMES:
            raise ValueError(
                f"LLM_PROVIDERS lists {name!r}, which is not one of: {', '.join(PROVIDER_NAMES)}"
            )
        if name not in names:
            names.append(name)
    return names


def load_llm_settings(env: Mapping[str, str] | None = None) -> LLMSettings:
    """Reads the provider settings.

    A listed provider without an API key is skipped with a warning (so one key can be added later without
    editing the list). Providers that are not listed are ignored even when their key is set.

    Args:
        env: Variables to read; the process environment when omitted.

    Returns:
        The settings.

    Raises:
        ValueError: ``LLM_PROVIDERS`` has an unknown name, or a timing variable is not a positive number.
        NoProviderConfiguredError: No listed provider has a key.
    """
    env = os.environ if env is None else env
    listed = parse_provider_list(env.get("LLM_PROVIDERS") or DEFAULT_PROVIDERS)
    if not listed:
        raise ValueError("LLM_PROVIDERS is set but lists no provider")

    usable: list[ProviderSettings] = []
    for name in listed:
        key = _first_value(env, KEY_VARIABLES[name])
        if not key:
            logger.warning(
                "LLM provider %r is in LLM_PROVIDERS but %s is empty: skipped", name, KEY_VARIABLES[name][0]
            )
            continue
        model = (env.get(MODEL_VARIABLES[name]) or "").strip() or DEFAULT_MODELS[name]
        usable.append(ProviderSettings(name=name, api_key=key, model=model))

    if not usable:
        keys = ", ".join(KEY_VARIABLES[name][0] for name in listed)
        raise NoProviderConfiguredError(f"No LLM provider can be used: set at least one of {keys}")

    return LLMSettings(
        providers=tuple(usable),
        timeout_seconds=_seconds(env, "LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        cooldown_seconds=_seconds(env, "LLM_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS),
    )
