"""Shared-secret checks for the HTTP surface.

Three independent secrets, each optional so local development stays frictionless;
set them in any deployment reachable from outside:

- ``API_TOKEN``: chat, agent tools and built-in tools (callers send ``X-API-Key``
  or ``Authorization: Bearer``). The backend sends it itself when an agent calls
  its own tools.
- ``WEBHOOK_TOKEN``: channel webhooks such as GoHighLevel's (send ``X-Webhook-Token``
  or ``Authorization: Bearer``; GHL's custom webhook action can add the header).
- ``ADMIN_TOKEN``: ``reset`` and ``admin/reload`` (see ``routes.require_admin``).
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated

from fastapi import Header, HTTPException, Request

from agent_backend.settings import Settings

logger = logging.getLogger("agent_backend")

API_KEY_HEADER = "X-API-Key"
WEBHOOK_HEADER = "X-Webhook-Token"


def _matches(expected: str, *candidates: str | None) -> bool:
    """Tells whether any candidate equals the expected secret (constant time).

    Args:
        expected: The configured secret.
        candidates: Raw header values; ``Authorization`` values may carry a ``Bearer `` prefix.

    Returns:
        True when one candidate matches.
    """
    for candidate in candidates:
        if not candidate:
            continue
        value = candidate.removeprefix("Bearer ").strip()
        if secrets.compare_digest(value.encode(), expected.encode()):
            return True
    return False


def require_api_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Dependency guarding chat and tool routes with ``API_TOKEN``.

    Args:
        request: Incoming request.
        authorization: ``Authorization`` header.
        x_api_key: ``X-API-Key`` header.

    Raises:
        HTTPException: 401 when a token is configured and the request lacks it.
    """
    settings: Settings = request.app.state.settings
    if settings.api_token and not _matches(settings.api_token, x_api_key, authorization):
        raise HTTPException(status_code=401, detail="Invalid or missing API token.")


def require_webhook_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_webhook_token: Annotated[str | None, Header()] = None,
) -> None:
    """Dependency guarding channel webhooks with ``WEBHOOK_TOKEN``.

    Args:
        request: Incoming request.
        authorization: ``Authorization`` header.
        x_webhook_token: ``X-Webhook-Token`` header.

    Raises:
        HTTPException: 401 when a token is configured and the request lacks it.
    """
    settings: Settings = request.app.state.settings
    if settings.webhook_token and not _matches(settings.webhook_token, x_webhook_token, authorization):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook token.")


def warn_about_open_endpoints(settings: Settings) -> None:
    """Logs one warning per secret that is not configured.

    Args:
        settings: Process settings.
    """
    for name, value in (
        ("API_TOKEN", settings.api_token),
        ("WEBHOOK_TOKEN", settings.webhook_token),
        ("ADMIN_TOKEN", settings.admin_token),
    ):
        if not value:
            logger.warning(
                "%s is not set: the routes it protects are open to anyone who can reach this port.", name
            )
