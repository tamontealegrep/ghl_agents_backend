"""Cliente HTTP de Croma (https://docs.usecroma.com) para la consulta de afiliación de ADRES."""

from __future__ import annotations

from typing import Any

import httpx

AFFILIATION_PATH = "/co/adres/affiliation-status/v1"


class CromaError(Exception):
    """The provider could not answer (network, credentials, quota, a lookup that did not finish)."""


def _error_message(response: httpx.Response) -> str:
    """Reads the provider's ``{"error": {"type", "code", "message"}}`` body, if there is one."""
    try:
        error = response.json().get("error") or {}
    except (ValueError, AttributeError):
        error = {}
    detail = error.get("message") or error.get("code") or error.get("type")
    return f"Croma answered HTTP {response.status_code}" + (f": {detail}" if detail else ".")


async def lookup_affiliation(
    body: dict[str, str],
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Asks Croma for the BDUA affiliation status of one document.

    The lookup is live (it reads ADRES at request time), so the request waits for the answer; the provider
    wraps it as ``{"data": {...}}``. A ``202`` means the lookup became an asynchronous job, which this tool does
    not poll.

    Args:
        body: ``{"document_type", "document_number"}`` as ``prepare_lookup`` built it.
        api_key: Croma API key (sent as a bearer token).
        base_url: Provider root, without a trailing slash.
        timeout_seconds: How long to wait for the answer.
        client: HTTP client to use (tests); a new one is created otherwise.

    Returns:
        The ``data`` object of the response.

    Raises:
        CromaError: Network failure, timeout, an error status or an unfinished lookup.
    """
    url = f"{base_url.rstrip('/')}{AFFILIATION_PATH}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        if client is not None:
            response = await client.post(url, json=body, headers=headers, timeout=timeout_seconds)
        else:
            async with httpx.AsyncClient() as own_client:
                response = await own_client.post(url, json=body, headers=headers, timeout=timeout_seconds)
    except httpx.TimeoutException as exc:
        raise CromaError(f"Croma did not answer within {timeout_seconds:g} seconds.") from exc
    except httpx.HTTPError as exc:
        raise CromaError(f"Could not reach Croma: {exc.__class__.__name__}.") from exc

    if response.status_code == 202:
        raise CromaError("The ADRES lookup did not finish in time (Croma answered 202); try again.")
    if response.status_code >= 400:
        raise CromaError(_error_message(response))
    try:
        payload = response.json()
    except ValueError as exc:
        raise CromaError("Croma answered with something that is not JSON.") from exc
    data = payload.get("data", payload) if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise CromaError("Croma answered with an unexpected body.")
    return data
