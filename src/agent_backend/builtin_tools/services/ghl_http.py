"""One way to call the GoHighLevel API from the built-in tools: the location's token, the right headers, and errors that come back as data."""

import logging
from typing import Any

import httpx

from agent_backend.channels.ghl.client import get_ghl_headers, ghl_client_config_for_location

logger = logging.getLogger(__name__)

_ERROR_BODY_CHARS = 300
"""How much of GHL's error body goes back to the agent (enough to see why, never a page of HTML)."""


async def ghl_call(
    method: str, path: str, *, location_id: str | None, body: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """Calls the GHL API with the token that owns `location_id`.

    The call never raises: a failure is returned as text so the tool can report it to the agent.

    Args:
        method: HTTP method (``POST``, ``PUT``, ``DELETE``...).
        path: Path under the API root, starting with ``/`` (``/contacts/<id>/tags``).
        location_id: GHL location (sub-account) the call is for: it picks the token.
        body: JSON body, if the endpoint takes one (``DELETE /contacts/{id}/tags`` does).

    Returns:
        ``(response_json, None)`` when GHL answered 2xx, else ``(None, reason)`` with the HTTP status and the start of
        GHL's answer, or the network error.
    """
    config = ghl_client_config_for_location(location_id)
    url = f"{config.base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=config.send_message_timeout_seconds) as client:
            response = await client.request(method, url, headers=get_ghl_headers(config), json=body)
            response.raise_for_status()
            return response.json(), None
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:_ERROR_BODY_CHARS]
        logger.warning("GHL %s %s failed: HTTP %s %s", method, path, exc.response.status_code, detail)
        return None, f"GHL returned HTTP {exc.response.status_code}: {detail}"
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("GHL %s %s failed: %s", method, path, exc)
        return None, str(exc) or exc.__class__.__name__
