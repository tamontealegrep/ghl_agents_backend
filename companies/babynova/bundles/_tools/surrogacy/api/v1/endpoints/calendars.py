from fastapi import APIRouter

from ....core.config import get_settings

router = APIRouter()


@router.get("/calendars")
async def list_calendars() -> dict[str, list[dict[str, object]]]:
    """Lists the calendars declared in the environment.

    Returns:
        One entry per calendar with its ``key`` and which integrations have an id
        configured. Ids and credentials are never returned.
    """
    return {
        "calendars": [
            {"key": key, "ghl": bool(tool.ghl_calendar_id), "google": bool(tool.calendar_id)}
            for key, tool in get_settings().calendars.items()
        ]
    }
