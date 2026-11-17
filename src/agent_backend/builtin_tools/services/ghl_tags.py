"""GoHighLevel contact tags used by the built-in tools."""

import ast
import json
import logging
import re
from typing import Any

import httpx

from agent_backend.channels.ghl.client import get_ghl_headers, ghl_client_config_for_location

logger = logging.getLogger(__name__)

_ERROR_BODY_CHARS = 300
"""How much of GHL's error body goes back to the agent (enough to see why, never a page of HTML)."""


def normalize_tags(raw: Any) -> list[str]:
    """Turns whatever the agent sent into the list of tags to add.

    The tags arrive as a list, or as a string when they come from a slot: a JSON or Python list
    (``'["vip", "nuevo"]'``) or names separated by commas or new lines. Each tag is trimmed, blanks are
    dropped and repeats removed (comparing without case, since GHL stores tags in lower case), keeping the order.

    Args:
        raw: A list of tags, or a string holding them.

    Returns:
        The tags, trimmed and without blanks or repeats; empty when there are none.
    """
    if isinstance(raw, str):
        text = raw.strip()
        items: Any = None
        if text.startswith("["):
            for parse in (json.loads, ast.literal_eval):
                try:
                    items = parse(text)
                    break
                except (ValueError, SyntaxError):
                    continue
        raw = items if isinstance(items, (list, tuple)) else re.split(r"[,\n]", text)
    tags: list[str] = []
    seen: set[str] = set()
    for item in raw or []:
        tag = str(item).strip()
        if tag and tag.lower() not in seen:
            seen.add(tag.lower())
            tags.append(tag)
    return tags


async def add_tags_service(tags: Any, contact_id: str, location_id: str | None = None) -> dict[str, Any]:
    """Adds tags to a GoHighLevel contact (``POST /contacts/{contactId}/tags``).

    GHL trims and lower-cases the tags, creates the ones the location does not have yet and ignores the ones the
    contact already has, so calling it again with the same tags is safe. The call needs the ``contacts.write``
    scope on the token of the contact's location.

    Args:
        tags: The tags to add (see ``normalize_tags`` for the accepted shapes).
        contact_id: GHL id of the contact.
        location_id: GHL location (sub-account) of the contact: it picks the token that owns it.

    Returns:
        ``success``; on success ``tags`` (every tag the contact has now) and ``tags_added`` (the new ones); on failure
        ``errors`` with the reason. It never raises: a failed call is reported, not thrown.
    """
    clean = normalize_tags(tags)
    if not (contact_id or "").strip():
        return {"success": False, "errors": "contact_id is required"}
    if not clean:
        return {"success": False, "errors": "No tags to add"}

    config = ghl_client_config_for_location(location_id)
    url = f"{config.base_url}/contacts/{contact_id.strip()}/tags"
    try:
        async with httpx.AsyncClient(timeout=config.send_message_timeout_seconds) as client:
            response = await client.post(url, headers=get_ghl_headers(config), json={"tags": clean})
            response.raise_for_status()
            body = response.json()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:_ERROR_BODY_CHARS]
        logger.warning("GHL add tags failed for contact %s: HTTP %s %s", contact_id, exc.response.status_code, detail)
        return {"success": False, "errors": f"GHL returned HTTP {exc.response.status_code}: {detail}"}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("GHL add tags failed for contact %s: %s", contact_id, exc)
        return {"success": False, "errors": str(exc) or exc.__class__.__name__}

    return {"success": True, "tags": body.get("tags", []), "tags_added": body.get("tagsAdded", [])}
