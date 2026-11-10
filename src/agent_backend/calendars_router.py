"""The ``GET /calendars`` tool every company's plugin exposes.

It lists the calendar keys a company declared in its environment (the values the
scheduling tools accept as ``calendar_type``) without leaking ids or credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter


def build_calendars_router(get_settings: Callable[[], Any]) -> APIRouter:
    """Builds the router that lists a company's calendars.

    Args:
        get_settings: Returns the plugin settings; it is called on every request, so
            tests and reloads see the current ones. The result needs a ``calendars``
            mapping of key to a tool config with ``ghl_calendar_id`` and ``calendar_id``.

    Returns:
        A router with ``GET /calendars``.
    """
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

    return router
