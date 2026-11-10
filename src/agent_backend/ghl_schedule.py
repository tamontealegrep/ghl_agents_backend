"""Reads a calendar's scheduling rules from GoHighLevel itself.

A company may leave the scheduling variables of a calendar empty (``<PREFIX>_DURATION_MINUTES_<KEY>``,
``..._PRE_BUFFER_MINUTES_...``, ``..._POST_BUFFER_MINUTES_...``, ``..._MIN_NOTICE_MINUTES_...``,
``..._DATE_RANGE_DAYS_...``). Those fields are then taken from the GHL calendar
(``slotDuration``, ``preBuffer``, ``slotBuffer``, ``allowBookingAfter``, ``allowBookingFor``), so the
rules are defined once, in GHL. A value written in the ``.env`` always wins.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from agent_backend import ghl_calendar
from agent_backend.calendars import CalendarSettings

logger = logging.getLogger(__name__)

__all__ = ["Schedule", "clear_cache", "resolve_schedule", "schedule_from_calendar", "to_days", "to_minutes"]

CACHE_SECONDS = 300
_MINUTES_PER_UNIT = {
    "min": 1,
    "mins": 1,
    "minute": 1,
    "minutes": 1,
    "hour": 60,
    "hours": 60,
    "day": 1440,
    "days": 1440,
    "week": 10080,
    "weeks": 10080,
    "month": 43200,
    "months": 43200,
}
_cache: dict[str, tuple[float, Mapping[str, Any]]] = {}


@dataclass(frozen=True)
class Schedule:
    """The scheduling rules to apply to one calendar.

    Attributes:
        duration_minutes: Appointment length.
        interval_minutes: Minimum distance between offered slot starts; 0 offers every slot.
        pre_buffer_minutes: Free time kept before each existing appointment.
        post_buffer_minutes: Free time kept after each existing appointment.
        min_notice_minutes: Minimum notice, or None for the company's own rule.
        date_range_days: How many days ahead slots are offered.
        from_ghl: Fields that were taken from the GHL calendar.
    """

    duration_minutes: int
    interval_minutes: int
    pre_buffer_minutes: int
    post_buffer_minutes: int
    min_notice_minutes: int | None
    date_range_days: int
    from_ghl: frozenset[str] = frozenset()


def to_minutes(value: Any, unit: Any) -> int | None:
    """Converts a GHL amount and unit to minutes.

    Args:
        value: Amount, e.g. ``15``.
        unit: Unit name (``mins``, ``hours``, ``days``, ``weeks``, ``months``); empty means minutes.

    Returns:
        Whole minutes (a month counts as 30 days), or None when the amount is missing or the unit unknown.
    """
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    factor = _MINUTES_PER_UNIT.get(str(unit or "mins").strip().lower())
    return None if factor is None else int(value * factor)


def to_days(value: Any, unit: Any) -> int | None:
    """Converts a GHL amount and unit to whole days.

    Args:
        value: Amount.
        unit: Unit name.

    Returns:
        Days rounded up, or None when the amount is missing or the unit unknown.
    """
    minutes = to_minutes(value, unit or "days")
    return None if minutes is None else -(-minutes // 1440)


def schedule_from_calendar(calendar: Mapping[str, Any], tool: CalendarSettings) -> Schedule:
    """Builds the schedule of a calendar from its GHL settings and its ``.env`` values.

    Args:
        calendar: The ``calendar`` object returned by GHL's Get Calendar.
        tool: The calendar's settings; ``read_from_ghl`` says which fields come from GHL.

    Returns:
        The schedule. A field GHL does not define keeps the ``.env`` (or default) value.
    """
    wanted = tool.read_from_ghl if calendar else frozenset()  # nothing to read from an empty answer
    found: dict[str, int | None] = {
        "duration_minutes": to_minutes(calendar.get("slotDuration"), calendar.get("slotDurationUnit")),
        "pre_buffer_minutes": to_minutes(calendar.get("preBuffer") or 0, calendar.get("preBufferUnit")),
        "post_buffer_minutes": to_minutes(calendar.get("slotBuffer") or 0, calendar.get("slotBufferUnit")),
        "min_notice_minutes": to_minutes(
            calendar.get("allowBookingAfter") or 0, calendar.get("allowBookingAfterUnit")
        ),
        "date_range_days": to_days(calendar.get("allowBookingFor"), calendar.get("allowBookingForUnit"))
        or None,  # 0 = no limit
    }
    taken = {name for name in wanted if found.get(name) is not None}

    def pick(name: str) -> int:
        value = found[name] if name in taken else getattr(tool, name)
        return int(value or 0)

    return Schedule(
        duration_minutes=pick("duration_minutes"),
        interval_minutes=tool.interval_minutes,
        pre_buffer_minutes=pick("pre_buffer_minutes"),
        post_buffer_minutes=pick("post_buffer_minutes"),
        min_notice_minutes=pick("min_notice_minutes"),
        date_range_days=pick("date_range_days"),
        from_ghl=frozenset(taken),
    )


def clear_cache() -> None:
    """Forgets every cached GHL calendar (used by tests and after changing a calendar in GHL)."""
    _cache.clear()


async def resolve_schedule(
    tool: CalendarSettings,
    token: str,
    *,
    get_calendar: Callable[..., Awaitable[Any]] | None = None,
) -> Schedule:
    """Returns the schedule to apply to a calendar, reading GHL only when a field was left empty.

    Args:
        tool: The calendar's settings.
        token: GHL token of the company.
        get_calendar: Replacement for ``ghl_calendar.get_calendar`` (tests).

    Returns:
        The schedule. If the GHL calendar cannot be read, the ``.env`` values and defaults are used and
        the problem is logged.
    """
    if not tool.read_from_ghl or not tool.ghl_calendar_id:
        return schedule_from_calendar({}, tool)

    cached = _cache.get(tool.ghl_calendar_id)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return schedule_from_calendar(cached[1], tool)

    fetch = get_calendar or ghl_calendar.get_calendar
    try:
        data = await fetch(token, tool.ghl_calendar_id)
    except Exception as exc:
        logger.warning(
            "Could not read the GHL calendar settings; using the .env values and defaults: %s", exc
        )
        return schedule_from_calendar({}, tool)
    calendar = data.get("calendar", data) if isinstance(data, Mapping) else {}
    _cache[tool.ghl_calendar_id] = (time.monotonic(), calendar)
    return schedule_from_calendar(calendar, tool)
