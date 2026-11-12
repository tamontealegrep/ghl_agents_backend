"""Google Gemini adapter (google-genai SDK)."""

from __future__ import annotations

from typing import Any

from .base import Provider, parse_json_object


class GeminiProvider(Provider):
    """Gemini models. Structured output uses the JSON-schema response mode."""

    name = "gemini"

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        """Creates the Gemini client."""
        super().__init__(model)
        from google import genai  # local import: importing this package never requires the SDK
        from google.genai import types

        self._types = types
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000))
        )

    def _complete(self, prompt: str, temperature: float) -> str:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self._types.GenerateContentConfig(temperature=temperature),
        )
        return response.text or ""

    def _extract(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        response = self._client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self._types.GenerateContentConfig(
                temperature=0,
                response_mime_type="application/json",
                response_json_schema=json_schema,
            ),
        )
        return parse_json_object(response.text)
