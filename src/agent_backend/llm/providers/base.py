"""Base of the provider adapters."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from ..errors import LLMProviderError, classify_exception

__all__ = ["Provider", "parse_json_object"]


def parse_json_object(text: str | None) -> dict[str, Any]:
    """Parses a model's JSON answer; an empty or malformed one is ``{}`` (nothing extracted), like the runtime expects."""
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


class Provider(ABC):
    """One LLM provider behind the runtime's two operations.

    Subclasses implement ``_complete`` and ``_extract``; this class turns any exception they raise into an
    ``LLMProviderError`` so callers see one error type whatever SDK sits underneath. A subclass keeps its SDK
    import inside ``__init__`` so the module imports without that SDK installed.
    """

    name: str

    def __init__(self, model: str) -> None:
        """Remembers the model this provider calls."""
        self.model = model

    @abstractmethod
    def _complete(self, prompt: str, temperature: float) -> str: ...

    @abstractmethod
    def _extract(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]: ...

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        """Plain text completion.

        Raises:
            LLMProviderError: The provider call failed.
        """
        try:
            return self._complete(prompt, temperature).strip()
        except LLMProviderError:
            raise
        except Exception as exc:
            raise classify_exception(self.name, exc) from exc

    def extract_structured(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        """Object that follows ``json_schema``.

        Raises:
            LLMProviderError: The provider call failed.
        """
        try:
            return self._extract(prompt, json_schema)
        except LLMProviderError:
            raise
        except Exception as exc:
            raise classify_exception(self.name, exc) from exc
