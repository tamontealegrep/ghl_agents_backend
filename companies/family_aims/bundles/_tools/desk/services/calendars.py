"""Resolves a ``calendar_type`` request value to a calendar's credentials and rules.

A calendar exists when its id is declared in the environment (see
``core.config.discover_calendar_keys``). IVF and SUR use their own policy modules;
every other calendar gets its rules from ``config/calendars.yaml``.
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Mapping, Optional, Tuple

from ..core.config import CALENDARS_PATH, ToolConfig
from . import booking_ivf, booking_sur, slots_ivf, slots_sur

Window = Tuple[int, int, int, int]

_BUILTIN_POLICIES = {"IVF": (booking_ivf, slots_ivf), "SUR": (booking_sur, slots_sur)}


@lru_cache
def load_calendars_config() -> dict[str, Any]:
    """Reads ``config/calendars.yaml``.

    Returns:
        The parsed file, or an empty default when the file is missing.
    """
    if not CALENDARS_PATH.exists():
        return {"default": {}, "calendars": {}}
    with open(CALENDARS_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class ConfiguredBooking:
    """Booking rules of a calendar declared in ``calendars.yaml``.

    Attributes:
        AGENT_NAME: Name shown in the confirmation email.
        EVENT_SUMMARY_TAG: Tag in the event title, ``Family Aims (<tag>) and <name>``.
        EMAIL_TEMPLATE_PREFIX: Email template prefix, or ``None`` to send no email.
    """

    def __init__(self, key: str, rules: Mapping[str, Any]) -> None:
        """Builds the rules.

        Args:
            key: Calendar key; the default event tag.
            rules: Merged ``default`` + calendar entry.
        """
        self.AGENT_NAME: str = rules.get("agent_name") or "Family Aims"
        self.EVENT_SUMMARY_TAG: str = rules.get("event_summary_tag") or key
        self.EMAIL_TEMPLATE_PREFIX: Optional[str] = rules.get("email_template_prefix")
        self._hours: Mapping[int, list[int]] = rules.get("hours") or {}
        lunch = rules.get("lunch_break") or {}
        self._lunch = (lunch.get("start_hour", 12), lunch.get("end_hour", 13))

    def is_valid_business_hour(self, weekday: int, hour: int, minute: int) -> bool:
        """Tells whether a booking may start at this time.

        Args:
            weekday: 0 = Sunday ... 6 = Saturday.
            hour: Hour, 0-23.
            minute: Minute, 0-59.

        Returns:
            True when the weekday is open, the time is inside its window (the end
            is inclusive at minute 0) and the hour is not a lunch hour.
        """
        window = self._hours.get(weekday)
        if not window:
            return False
        start_h, start_m, end_h, end_m = window
        if self._lunch[0] <= hour < self._lunch[1]:
            return False
        return (start_h, start_m) <= (hour, minute) <= (end_h, end_m)


class ConfiguredSlots:
    """Slot rules of a calendar declared in ``calendars.yaml``."""

    def __init__(self, rules: Mapping[str, Any]) -> None:
        """Builds the rules.

        Args:
            rules: Merged ``default`` + calendar entry.
        """
        self._hours: Mapping[int, list[int]] = rules.get("hours") or {}
        lunch = rules.get("lunch_break") or {}
        self._lunch = (lunch.get("start_hour", 12), lunch.get("end_hour", 13))

    def day_window(self, weekday: int) -> Optional[Window]:
        """Returns the opening window of a weekday.

        Args:
            weekday: 0 = Sunday ... 6 = Saturday.

        Returns:
            ``(start_hour, start_minute, end_hour, end_minute)``, or None when closed.
        """
        window = self._hours.get(weekday)
        return tuple(window) if window else None  # type: ignore[return-value]

    def lunch_break(self, start_min: int, end_min: int) -> bool:
        """Tells whether a slot overlaps the lunch break.

        Args:
            start_min: Slot start, in minutes since midnight.
            end_min: Slot end, in minutes since midnight.

        Returns:
            True when the slot must be excluded: it starts before the break ends and ends after it starts.
            A break without duration excludes nothing.
        """
        lunch_start, lunch_end = self._lunch[0] * 60, self._lunch[1] * 60
        return lunch_start < lunch_end and start_min < lunch_end and end_min > lunch_start

    def closing_hour(self, weekday: int) -> Tuple[int, int]:
        """Returns the time the search range closes on a weekday.

        Args:
            weekday: 0 = Sunday ... 6 = Saturday.

        Returns:
            ``(hour, minute)`` of the window end; 17:00 when the day is closed.
        """
        window = self.day_window(weekday)
        return (window[2], window[3]) if window else (17, 0)


@dataclass(frozen=True)
class CalendarContext:
    """Everything an endpoint needs to work with one calendar.

    Attributes:
        key: Upper-case calendar key, e.g. ``"IVF"``.
        tool: Credentials, calendar ids and durations.
        booking: Booking rules (hours, agent name, email template).
        slots: Slot rules (windows, lunch break, closing hour).
    """

    key: str
    tool: ToolConfig
    booking: Any
    slots: Any


def available_keys(settings: Any) -> list[str]:
    """Lists the calendar keys the deployment knows.

    Args:
        settings: Plugin settings.

    Returns:
        Upper-case keys.
    """
    return list(settings.calendars)


def resolve_calendar(settings: Any, calendar_type: Optional[str], config: Optional[Mapping[str, Any]] = None) -> Optional[CalendarContext]:
    """Finds a calendar by the ``calendar_type`` a tool call sent.

    Args:
        settings: Plugin settings.
        calendar_type: Value from the request, any letter case. Empty means ``IVF``.
        config: ``calendars.yaml`` contents; defaults to the file on disk.

    Returns:
        The calendar's context, or None when no such calendar is declared.
    """
    key = (calendar_type or "IVF").strip().upper()
    tool = settings.calendars.get(key)
    if tool is None:
        return None
    if key in _BUILTIN_POLICIES:
        booking, slots = _BUILTIN_POLICIES[key]
        return CalendarContext(key, tool, booking, slots)

    cfg = load_calendars_config() if config is None else config
    entries = {str(k).upper(): v for k, v in (cfg.get("calendars") or {}).items()}
    rules = {**(cfg.get("default") or {}), **(entries.get(key) or {})}
    return CalendarContext(key, tool, ConfiguredBooking(key, rules), ConfiguredSlots(rules))


def unknown_calendar_message(settings: Any, calendar_type: Optional[str]) -> str:
    """Builds the error for a calendar that is not declared.

    Args:
        settings: Plugin settings.
        calendar_type: The value the caller sent.

    Returns:
        A message that lists the valid keys.
    """
    return f"Unknown calendar_type '{calendar_type}'. Valid values: {', '.join(available_keys(settings))}"
