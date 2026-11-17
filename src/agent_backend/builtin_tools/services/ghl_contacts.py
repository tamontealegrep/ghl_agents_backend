"""Updating a GoHighLevel contact from the built-in tools."""

from typing import Any

from agent_backend.builtin_tools.services import ghl as custom_field_helpers
from agent_backend.builtin_tools.services.ghl_custom_fields import normalize_custom_fields
from agent_backend.builtin_tools.services.ghl_http import ghl_call
from agent_backend.channels.ghl.client import get_ghl_headers, ghl_client_config_for_location

CONTACT_FIELDS: dict[str, str] = {
    "first_name": "firstName",
    "last_name": "lastName",
    "name": "name",
    "email": "email",
    "phone": "phone",
    "address1": "address1",
    "city": "city",
    "state": "state",
    "postal_code": "postalCode",
    "website": "website",
    "timezone": "timezone",
    "source": "source",
    "date_of_birth": "dateOfBirth",
    "country": "country",
    "assigned_to": "assignedTo",
    "dnd": "dnd",
}
"""The standard contact fields the tool can change: the name the agent uses -> the name GHL uses."""


def _looks_like_field_id(name: str) -> bool:
    """A GHL custom field id (long, with digits) rather than a readable name."""
    return len(name) >= 15 and any(c.isdigit() for c in name)


async def _resolve_custom_fields(
    pairs: list[tuple[str, str]], location_id: str | None
) -> tuple[list[dict[str, str]], list[str], str | None]:
    """Turns ``(name or id, value)`` pairs into the ``customFields`` GHL expects.

    A readable name (or field key) is looked up in the location's custom fields, and a value that is not one of the
    options of a dropdown field is refused, as ``update_custom_field`` does. An id is used as it is.

    Returns:
        ``(customFields, names updated, error)``; the error is set when a name cannot be resolved or a value is not
        an option, and then nothing should be sent.
    """
    resolved: list[dict[str, str]] = []
    names: list[str] = []
    config = ghl_client_config_for_location(location_id)
    headers = get_ghl_headers(config)
    for name, value in pairs:
        if _looks_like_field_id(name):
            resolved.append({"id": name, "fieldValue": value})
            names.append(name)
            continue
        if not location_id:
            return [], [], f"location_id is required to find the custom field '{name}' by name"
        field = await custom_field_helpers._find_custom_field_by_name(location_id, name, config, headers)
        if not field:
            return [], [], f"Custom field '{name}' not found"
        value = custom_field_helpers._as_option_values(field, value)
        invalid = custom_field_helpers._invalid_options(field, value)
        if invalid:
            allowed = ", ".join(field["picklistOptions"])
            return [], [], f"Invalid value(s) {invalid} for '{name}'. Allowed: {allowed}"
        resolved.append({"id": field["id"], "fieldValue": value})
        names.append(name)
    return resolved, names, None


async def update_contact_service(
    contact_id: str,
    location_id: str | None = None,
    fields: dict[str, Any] | None = None,
    custom_fields: Any = None,
) -> dict[str, Any]:
    """Updates a GoHighLevel contact (``PUT /contacts/{contactId}``).

    Only what is given is sent, so every other field keeps its value. Tags are not touched here: GHL would replace
    all of them, so they are changed with ``add_tags`` and ``remove_tags``. Needs the ``contacts.write`` scope.

    Args:
        contact_id: GHL id of the contact.
        location_id: GHL location (sub-account): it picks the token, and is needed to find custom fields by name.
        fields: Standard fields to change, by the names in ``CONTACT_FIELDS``; ``None`` values are ignored.
        custom_fields: Custom fields to change (see ``normalize_custom_fields`` for the accepted shapes).

    Returns:
        ``success``, ``contact_id`` and ``updated_fields`` (what was sent); on failure ``errors`` with the reason.
        It never raises.
    """
    if not (contact_id or "").strip():
        return {"success": False, "errors": "contact_id is required"}
    payload: dict[str, Any] = {}
    updated: list[str] = []
    for name, value in (fields or {}).items():
        if value is None or name not in CONTACT_FIELDS:
            continue
        payload[CONTACT_FIELDS[name]] = value.strip() if isinstance(value, str) else value
        updated.append(name)
    pairs = normalize_custom_fields(custom_fields)
    if pairs:
        resolved, names, error = await _resolve_custom_fields(pairs, location_id)
        if error:
            return {"success": False, "contact_id": contact_id.strip(), "errors": error}
        payload["customFields"] = resolved
        updated += names
    if not payload:
        return {"success": False, "contact_id": contact_id.strip(), "errors": "Nothing to update"}

    body, error = await ghl_call("PUT", f"/contacts/{contact_id.strip()}", location_id=location_id, body=payload)
    if error or body is None:
        return {"success": False, "contact_id": contact_id.strip(), "errors": error or "Empty response"}
    if body.get("succeeded") is False:
        return {"success": False, "contact_id": contact_id.strip(), "errors": "GHL did not accept the update"}
    return {"success": True, "contact_id": contact_id.strip(), "updated_fields": updated}
