"""Errors of the multi-provider LLM client and the rules that sort a provider failure into a kind.

Every provider SDK raises its own exceptions. The providers catch them and re-raise an
``LLMProviderError`` whose ``kind`` says why the call failed, so the failover client decides what
to do from one vocabulary instead of knowing three SDKs.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "AllProvidersFailedError",
    "ErrorKind",
    "LLMProviderError",
    "NoProviderConfiguredError",
    "classify_exception",
]


class ErrorKind(StrEnum):
    """Why a provider call failed."""

    AUTH = "auth"  # missing, wrong or revoked key
    QUOTA = "quota"  # out of credits, billing problem, hard spending limit
    RATE_LIMIT = "rate_limit"  # too many requests right now
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"  # provider outage, 5xx, network failure
    BAD_REQUEST = "bad_request"  # the provider refused this particular request
    UNKNOWN = "unknown"


class LLMProviderError(Exception):
    """A call to one provider failed.

    Attributes:
        provider: Provider name (``openai``, ``anthropic``, ``google``).
        kind: Why it failed.
        detail: The SDK's own message.
    """

    def __init__(self, provider: str, kind: ErrorKind, detail: str) -> None:
        """Records which provider failed and why."""
        super().__init__(f"{provider}: {kind.value}: {detail}")
        self.provider = provider
        self.kind = kind
        self.detail = detail


class AllProvidersFailedError(RuntimeError):
    """Every configured provider failed the same call.

    Attributes:
        attempts: One error per provider tried, in the order they were tried.
    """

    def __init__(self, attempts: list[LLMProviderError]) -> None:
        """Keeps the per-provider errors."""
        self.attempts = attempts
        summary = "; ".join(f"{e.provider} ({e.kind.value})" for e in attempts) or "no provider was tried"
        super().__init__(f"All LLM providers failed: {summary}")


class NoProviderConfiguredError(RuntimeError):
    """No provider in ``LLM_PROVIDERS`` has an API key."""


_QUOTA_WORDS = (
    "insufficient_quota",
    "insufficient quota",
    "exceeded your current quota",
    "credit balance",
    "billing",
    "out of credits",
    "resource_exhausted",
    "spending limit",
)


_AUTH_WORDS = (
    "api key not valid",
    "api_key_invalid",
    "invalid x-api-key",
    "incorrect api key",
    "invalid api key",
)


def _status_of(exc: BaseException) -> int | None:
    """HTTP status carried by an SDK exception (``status_code`` for openai/anthropic, ``code`` for google-genai)."""
    for attribute in ("status_code", "code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    return None


def classify_exception(provider: str, exc: BaseException) -> LLMProviderError:
    """Turns whatever an SDK raised into an ``LLMProviderError``.

    Works on duck-typed attributes and class names so this module never imports an SDK.

    Args:
        provider: Provider that raised it.
        exc: The SDK exception.

    Returns:
        The same failure, with a kind.
    """
    if isinstance(exc, LLMProviderError):
        return exc
    text = str(exc)
    lowered = text.lower()
    status = _status_of(exc)
    names = " ".join(cls.__name__.lower() for cls in type(exc).__mro__)

    if status in (401, 403) or any(word in lowered for word in _AUTH_WORDS):
        # Gemini answers a wrong key with a 400, so the message has to be read too.
        kind = ErrorKind.AUTH
    elif status == 402 or any(word in lowered for word in _QUOTA_WORDS):
        # A 429 that says "quota" or "credit" is an empty account, not a momentary burst.
        kind = ErrorKind.QUOTA
    elif status == 429 or "ratelimit" in names:
        kind = ErrorKind.RATE_LIMIT
    elif status == 408 or "timeout" in names or "timed out" in lowered:
        kind = ErrorKind.TIMEOUT
    elif (status is not None and status >= 500) or "connection" in names or "unavailable" in names:
        kind = ErrorKind.UNAVAILABLE
    elif status in (400, 404, 413, 422):
        kind = ErrorKind.BAD_REQUEST
    else:
        kind = ErrorKind.UNKNOWN
    return LLMProviderError(provider, kind, text[:500])
