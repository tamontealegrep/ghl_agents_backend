"""GoHighLevel contact tags used by the built-in tools."""

import ast
import json
import re
from typing import Any

from agent_backend.builtin_tools.services.ghl_http import ghl_call


def normalize_tags(raw: Any) -> list[str]:
    """Turns whatever the agent sent into the list of tags.

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


def _check(tags: Any, contact_id: str) -> tuple[list[str], dict[str, Any] | None]:
    """The clean tags, or the failure to report when there is no contact or nothing to do."""
    clean = normalize_tags(tags)
    if not (contact_id or "").strip():
        return clean, {"success": False, "errors": "contact_id is required"}
    if not clean:
        return clean, {"success": False, "errors": "No tags"}
    return clean, None


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
    clean, failure = _check(tags, contact_id)
    if failure:
        return failure
    body, error = await ghl_call(
        "POST", f"/contacts/{contact_id.strip()}/tags", location_id=location_id, body={"tags": clean}
    )
    if error or body is None:
        return {"success": False, "errors": error or "Empty response"}
    return {"success": True, "tags": body.get("tags", []), "tags_added": body.get("tagsAdded", [])}


async def remove_tags_service(tags: Any, contact_id: str, location_id: str | None = None) -> dict[str, Any]:
    """Removes tags from a GoHighLevel contact (``DELETE /contacts/{contactId}/tags``).

    GHL lower-cases the tags before matching and ignores the ones the contact does not have, so asking for a tag
    that is not there is not an error. Only the tags named are removed. The call needs the ``contacts.write`` scope.

    Args:
        tags: The tags to remove (see ``normalize_tags`` for the accepted shapes).
        contact_id: GHL id of the contact.
        location_id: GHL location (sub-account) of the contact: it picks the token that owns it.

    Returns:
        ``success``; on success ``tags`` (the tags left on the contact) and ``tags_removed`` (the ones that were there
        and are gone); on failure ``errors`` with the reason. It never raises.
    """
    clean, failure = _check(tags, contact_id)
    if failure:
        return failure
    body, error = await ghl_call(
        "DELETE", f"/contacts/{contact_id.strip()}/tags", location_id=location_id, body={"tags": clean}
    )
    if error or body is None:
        return {"success": False, "errors": error or "Empty response"}
    return {"success": True, "tags": body.get("tags", []), "tags_removed": body.get("tagsRemoved", [])}
