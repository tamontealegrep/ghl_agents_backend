"""Anthropic Messages API adapter (Claude)."""

from __future__ import annotations

from typing import Any

from .base import Provider

MAX_OUTPUT_TOKENS = 4096
EXTRACTION_TOOL = "extraction"


class AnthropicProvider(Provider):
    """Claude models. Structured output is a forced tool call whose input schema is the requested JSON schema."""

    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        """Creates the Anthropic client."""
        super().__init__(model)
        from anthropic import Anthropic  # local import: importing this package never requires the SDK

        self._client = Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=1)

    def _complete(self, prompt: str, temperature: float) -> str:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")

    def _extract(self, prompt: str, json_schema: dict[str, Any]) -> dict[str, Any]:
        response = self._client.messages.create(
            model=self.model,
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": EXTRACTION_TOOL,
                    "description": "Record the values extracted from the message.",
                    "input_schema": json_schema,
                }
            ],
            tool_choice={"type": "tool", "name": EXTRACTION_TOOL},
        )
        for block in response.content:
            payload = getattr(block, "input", None) if getattr(block, "type", "") == "tool_use" else None
            if isinstance(payload, dict):
                return dict(payload)
        return {}
