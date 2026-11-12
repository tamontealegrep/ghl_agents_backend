"""OpenAI Chat Completions adapter."""

from __future__ import annotations

from typing import Any

from .base import Provider, parse_json_object


class OpenAIProvider(Provider):
    """OpenAI models. Structured output uses strict JSON-schema mode."""

    name = "openai"

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        """Creates the OpenAI client."""
        super().__init__(model)
        from openai import OpenAI  # local import: importing this package never requires the SDK

        # One SDK retry only: a provider that keeps failing should hand over to the next one quickly.
        self._client = OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=1)

    def _complete(self, prompt: str, temperature: float) -> str:
        response = self._client.chat.completions.create(
            model=self.model, messages=[{"role": "user", "content": prompt}], temperature=temperature
        )
        return response.choices[0].message.content or ""

    def _extract(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "extraction", "schema": json_schema, "strict": True},
            },
        )
        return parse_json_object(response.choices[0].message.content)
