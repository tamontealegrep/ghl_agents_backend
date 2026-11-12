"""LLM provider settings, read from the environment.

Variables:
    LLM_PROVIDERS                  Providers to use, most preferred first, comma separated
                                   (``openai,anthropic,google``). One left out of the list is never used.
                                   Required, no default: an empty or missing value is an error.
    OPENAI_API_KEY / OPENAI_MODEL
    ANTHROPIC_API_KEY / ANTHROPIC_MODEL
    GOOGLE_API_KEY / GOOGLE_MODEL  Gemini models, through Google's API.

A provider needs both its key and its model. There are no default models on purpose: vendors retire
models, and a silent default would keep pointing at one that no longer exists. A listed provider that
lacks either is ignored (with a warning); when none is left, loading the settings fails so the server
does not start.

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
    "KEY_VARIABLES",
    "PROVIDER_NAMES",
    "LLMSettings",
    "ProviderSettings",
    "load_llm_settings",
]

logger = logging.getLogger(__name__)

PROVIDER_NAMES = ("openai", "anthropic", "google")

KEY_VARIABLES = {"openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}
MODEL_VARIABLES = {"openai": "OPENAI_MODEL", "anthropic": "ANTHROPIC_MODEL", "google": "GOOGLE_MODEL"}

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

    A listed provider without its API key or its model is ignored with a warning (so it can be filled in later
    without editing the list). Providers that are not listed are ignored even when their key is set.

    Args:
        env: Variables to read; the process environment when omitted.

    Returns:
        The settings.

    Raises:
        ValueError: ``LLM_PROVIDERS`` has an unknown name, or a timing variable is not a positive number.
        NoProviderConfiguredError: ``LLM_PROVIDERS`` is empty, or no listed provider has both its key and its model.
    """
    env = os.environ if env is None else env
    listed = parse_provider_list(env.get("LLM_PROVIDERS") or "")
    if not listed:
        raise NoProviderConfiguredError(
            f"LLM_PROVIDERS is empty or missing. List the providers to use, most preferred first, "
            f"from: {', '.join(PROVIDER_NAMES)} (for example LLM_PROVIDERS=openai)"
        )

    usable: list[ProviderSettings] = []
    for name in listed:
        key = (env.get(KEY_VARIABLES[name]) or "").strip()
        model = (env.get(MODEL_VARIABLES[name]) or "").strip()
        missing = [
            var for var, value in ((KEY_VARIABLES[name], key), (MODEL_VARIABLES[name], model)) if not value
        ]
        if missing:
            logger.warning(
                "LLM provider %r is in LLM_PROVIDERS but %s is empty: ignored", name, " and ".join(missing)
            )
            continue
        usable.append(ProviderSettings(name=name, api_key=key, model=model))

    if not usable:
        needs = "; ".join(f"{name}: {KEY_VARIABLES[name]} and {MODEL_VARIABLES[name]}" for name in listed)
        raise NoProviderConfiguredError(
            f"No LLM provider can be used. Each provider listed in LLM_PROVIDERS needs its key and its model ({needs})"
        )

    return LLMSettings(
        providers=tuple(usable),
        timeout_seconds=_seconds(env, "LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS),
        cooldown_seconds=_seconds(env, "LLM_COOLDOWN_SECONDS", DEFAULT_COOLDOWN_SECONDS),
    )
