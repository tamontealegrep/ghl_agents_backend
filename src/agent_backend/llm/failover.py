"""An LLM client that falls back to the next provider when one fails."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from .config import TRANSIENT_COOLDOWN_SECONDS
from .errors import AllProvidersFailedError, ErrorKind, LLMProviderError
from .providers.base import Provider

__all__ = ["FailoverLLMClient"]

logger = logging.getLogger(__name__)

T = TypeVar("T")

_LONG_COOLDOWN = {ErrorKind.AUTH, ErrorKind.QUOTA}
_SHORT_COOLDOWN = {ErrorKind.RATE_LIMIT, ErrorKind.TIMEOUT, ErrorKind.UNAVAILABLE}


class FailoverLLMClient:
    """The runtime's ``LLMClient`` over several providers, tried in priority order.

    A call goes to the first provider that is not resting. When it fails, the next one answers the same call
    and the failed one rests, so the following calls do not wait for it again: a long rest for a bad key or no
    credits, a short one for a rate limit or an outage. A request the provider simply refused (bad request)
    moves on to the next provider but does not make the first one rest. Once the rest is over the preferred
    provider is tried again by itself. If every provider fails, the providers that were resting are tried
    too, as a last resort, before giving up.

    Attributes:
        last_provider: Provider that answered the most recent call (None before the first one).
    """

    def __init__(
        self,
        providers: Sequence[Provider],
        *,
        cooldown_seconds: float,
        transient_cooldown_seconds: float = TRANSIENT_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Takes the providers in priority order and the rest times."""
        if not providers:
            raise ValueError("FailoverLLMClient needs at least one provider")
        self._providers = tuple(providers)
        self._cooldown = cooldown_seconds
        self._transient_cooldown = transient_cooldown_seconds
        self._clock = clock
        self._resting_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self.last_provider: str | None = None

    # ------------------------------------------------------------------ LLMClient

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        """Plain completion from the first provider that answers.

        Raises:
            AllProvidersFailedError: Every provider failed.
        """
        return self._run(lambda provider: provider.complete(prompt, temperature=temperature))

    def extract_structured(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        """Structured extraction from the first provider that answers.

        Raises:
            AllProvidersFailedError: Every provider failed.
        """
        return self._run(lambda provider: provider.extract_structured(prompt, json_schema))

    # ------------------------------------------------------------------ status

    @property
    def model(self) -> str:
        """Model of the provider that answered last (the preferred provider's before any call)."""
        by_name = {p.name: p.model for p in self._providers}
        return by_name.get(self.last_provider or "", self._providers[0].model)

    @property
    def provider_names(self) -> list[str]:
        """Providers in priority order."""
        return [p.name for p in self._providers]

    def status(self) -> list[dict[str, Any]]:
        """Each provider's model and whether it is resting (and for how many more seconds)."""
        now = self._clock()
        with self._lock:
            return [
                {
                    "provider": p.name,
                    "model": p.model,
                    "resting_seconds": max(0, round(self._resting_until.get(p.name, 0) - now)),
                }
                for p in self._providers
            ]

    # ------------------------------------------------------------------ internals

    def _order(self) -> list[Provider]:
        now = self._clock()
        with self._lock:
            ready = [p for p in self._providers if self._resting_until.get(p.name, 0) <= now]
        resting = [p for p in self._providers if p not in ready]
        return ready + resting

    def _rest(self, error: LLMProviderError) -> None:
        if error.kind in _LONG_COOLDOWN:
            seconds = self._cooldown
        elif error.kind in _SHORT_COOLDOWN:
            seconds = self._transient_cooldown
        else:
            return
        with self._lock:
            self._resting_until[error.provider] = self._clock() + seconds

    def _run(self, call: Callable[[Provider], T]) -> T:
        attempts: list[LLMProviderError] = []
        for provider in self._order():
            try:
                result = call(provider)
            except LLMProviderError as error:
                attempts.append(error)
                self._rest(error)
                logger.warning(
                    "LLM provider %s failed (%s); trying the next one: %s",
                    error.provider,
                    error.kind.value,
                    error.detail,
                )
                continue
            if provider.name != self.last_provider:
                logger.info("LLM provider in use: %s (%s)", provider.name, provider.model)
            self.last_provider = provider.name
            return result
        raise AllProvidersFailedError(attempts)
