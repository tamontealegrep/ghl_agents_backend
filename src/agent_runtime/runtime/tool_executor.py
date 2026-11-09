"""
Generic tool executor — the concrete shape of DESIGN_PATTERNS.md P05.

    Given any `ToolContract` and one configured base URL, produces a callable
    that POSTs the declared inputs to `{base_url}/{tool.name}` and maps the
    JSON response onto the declared outputs. No tool ever gets a hand-written
    Python function (that's A04, the anti-pattern this replaces) — the
    agent/LLM only ever sees "call this function with these parameters."
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from agent_runtime.dsl.schemas import ToolContract


class ToolExecutionError(RuntimeError):
    """
Raised when a tool call fails — a non-2xx response or a transport error.
"""

def make_tool_executor(
    contract: ToolContract,
    base_url: str,
    *,
    client: httpx.Client | None = None,
    timeout: float = 30.0,
) -> Callable[..., dict[str, Any]]:
    """Build a callable that executes `contract` against `{base_url}/{contract.name}`.

    Args:
        contract: The tool's input/output interface — no
            endpoint/transport information, by design (see `ToolContract`'s
            own docstring). This function is the one place that resolves a
            contract to an actual HTTP call.
        base_url: The centralized tool endpoint's base URL (e.g. the
            deployment's `TOOLS_BASE_URL`).
        client: Injected for tests (e.g.
            `httpx.Client(transport=httpx.MockTransport(...))`); a fresh
            client is created and closed per call otherwise.
        timeout: Request timeout in seconds.

    Returns:
        Callable[..., dict[str, Any]]: Accepts the contract's declared input
        fields as keyword arguments, returns a dict keyed by the
        contract's declared output field names. An output missing from
        the response is simply omitted from the result — never
        fabricated.

    Raises:
        ValueError: If called with an unknown keyword or missing a required input.
        ToolExecutionError: If the HTTP call fails, returns a non-2xx status,
            or returns a body that isn't valid JSON.
    """
    url = f"{base_url.rstrip('/')}/{contract.name}"
    input_names = {f.name for f in contract.inputs}
    required_input_names = {f.name for f in contract.inputs if f.required}
    output_names = [f.name for f in contract.outputs]

    def call(**kwargs: Any) -> dict[str, Any]:
        unknown = set(kwargs) - input_names
        if unknown:
            raise ValueError(f"Unknown input(s) for tool {contract.name!r}: {sorted(unknown)}")
        missing_required = required_input_names - set(kwargs)
        if missing_required:
            raise ValueError(
                f"Missing required input(s) for tool {contract.name!r}: {sorted(missing_required)}"
            )

        owns_client = client is None
        http_client = client or httpx.Client(timeout=timeout)
        try:
            response = http_client.post(url, json=kwargs, timeout=timeout)
        except httpx.HTTPError as exc:
            raise ToolExecutionError(f"Tool {contract.name!r} call failed: {exc}") from exc
        finally:
            if owns_client:
                http_client.close()

        if response.status_code >= 400:
            raise ToolExecutionError(
                f"Tool {contract.name!r} returned HTTP {response.status_code}: {response.text}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise ToolExecutionError(f"Tool {contract.name!r} returned a non-JSON response") from exc

        return {name: payload[name] for name in output_names if name in payload}

    return call
