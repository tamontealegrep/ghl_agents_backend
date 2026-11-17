"""Updating a GoHighLevel opportunity from the built-in tools."""

from typing import Any

from agent_backend.builtin_tools.services.ghl_custom_fields import normalize_custom_fields
from agent_backend.builtin_tools.services.ghl_http import ghl_call

OPPORTUNITY_FIELDS: dict[str, str] = {
    "pipeline_id": "pipelineId",
    "name": "name",
    "pipeline_stage_id": "pipelineStageId",
    "status": "status",
    "monetary_value": "monetaryValue",
    "forecast_expected_close_date": "forecastExpectedCloseDate",
    "forecast_probability": "forecastProbability",
    "assigned_to": "assignedTo",
    "lost_reason_id": "lostReasonId",
}
"""The opportunity fields the tool can change: the name the agent uses -> the name GHL uses."""

STATUSES = ("open", "won", "lost", "abandoned")
_NUMBERS = ("monetary_value", "forecast_probability")
_CUSTOM_FIELD_PREFIX = "opportunity."


def _number(name: str, value: Any) -> tuple[float | int | None, str | None]:
    """`value` as a number (``"1,500.50"`` and ``"$300"`` are read), or the reason it is not one."""
    if isinstance(value, bool):
        return None, f"{name} must be a number"
    if isinstance(value, (int, float)):
        number: float | int = value
    else:
        try:
            number = float(str(value).replace(",", "").replace("$", "").strip())
        except ValueError:
            return None, f"{name} must be a number, got '{value}'"
    if name == "monetary_value" and number < 0:
        return None, "monetary_value must be 0 or more"
    return (int(number) if float(number).is_integer() else number), None


async def update_opportunity_service(
    opportunity_id: str,
    location_id: str | None = None,
    fields: dict[str, Any] | None = None,
    custom_fields: Any = None,
) -> dict[str, Any]:
    """Updates a GoHighLevel opportunity (``PUT /opportunities/{id}``).

    Only what is given is sent. ``status`` is one of ``open``, ``won``, ``lost`` and ``abandoned``;
    ``lost_reason_id`` counts only when the status is or becomes ``lost``. Custom fields are given by id or by key
    (without the ``opportunity.`` prefix, which is dropped if sent); one that matches no custom field of the location
    is ignored by GHL. Needs the ``opportunities.write`` scope.

    Args:
        opportunity_id: GHL id of the opportunity.
        location_id: GHL location (sub-account): it picks the token.
        fields: Fields to change, by the names in ``OPPORTUNITY_FIELDS``; ``None`` values are ignored.
        custom_fields: Custom fields to change (see ``normalize_custom_fields`` for the accepted shapes).

    Returns:
        ``success``, ``opportunity_id`` and ``updated_fields``, plus ``status``, ``pipeline_id``,
        ``pipeline_stage_id``, ``name`` and ``monetary_value`` as GHL now has them; on failure ``errors`` with the
        reason. It never raises.
    """
    if not (opportunity_id or "").strip():
        return {"success": False, "errors": "opportunity_id is required"}
    opportunity_id = opportunity_id.strip()
    payload: dict[str, Any] = {}
    updated: list[str] = []
    for name, value in (fields or {}).items():
        if value is None or name not in OPPORTUNITY_FIELDS:
            continue
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if name == "status":
            value = str(value).lower()
            if value not in STATUSES:
                return {"success": False, "opportunity_id": opportunity_id, "errors": f"status must be one of: {', '.join(STATUSES)}"}
        if name in _NUMBERS:
            value, error = _number(name, value)
            if error:
                return {"success": False, "opportunity_id": opportunity_id, "errors": error}
        payload[OPPORTUNITY_FIELDS[name]] = value
        updated.append(name)
    pairs = normalize_custom_fields(custom_fields)
    if pairs:
        payload["customFields"] = [
            {("id" if len(key) >= 15 and any(c.isdigit() for c in key) else "key"): key.removeprefix(_CUSTOM_FIELD_PREFIX), "fieldValue": value}
            for key, value in pairs
        ]
        updated += [key for key, _ in pairs]
    if not payload:
        return {"success": False, "opportunity_id": opportunity_id, "errors": "Nothing to update"}

    body, error = await ghl_call("PUT", f"/opportunities/{opportunity_id}", location_id=location_id, body=payload)
    if error or body is None:
        return {"success": False, "opportunity_id": opportunity_id, "errors": error or "Empty response"}
    now = body.get("opportunity") or {}
    return {
        "success": True,
        "opportunity_id": opportunity_id,
        "updated_fields": updated,
        "status": now.get("status"),
        "pipeline_id": now.get("pipelineId"),
        "pipeline_stage_id": now.get("pipelineStageId"),
        "name": now.get("name"),
        "monetary_value": now.get("monetaryValue"),
    }
