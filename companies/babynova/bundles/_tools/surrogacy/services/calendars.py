"""Resolves a ``calendar_type`` request value to a calendar's credentials and rules.

A calendar exists when one of its variables is declared in the environment (see
``agent_backend.calendars``). ``FT`` uses the rules in ``services/booking.py`` and
``config/slots.yaml``; every other calendar gets its rules from ``config/calendars.yaml``.
"""

from __future__ import annotations

import yaml
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, List, Mapping, Optional, Tuple

from agent_backend.calendars import CalendarSettings

from ..core.config import CALENDARS_PATH
from agent_backend.scheduling_schemas import Slot
from . import booking, slot_calculator

BUILTIN_RULES_KEY = "FT"
Window = Tuple[int, int, int, int]


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


def _plain_hours(key: str, raw: Mapping[Any, Any]) -> dict[int, Window]:
    """Validates the ``hours`` mapping of a configured calendar.

    Args:
        key: Calendar key, for error messages.
        raw: Weekday number to ``[start_hour, start_minute, end_hour, end_minute]``.

    Returns:
        The same mapping with integer keys and tuple windows.

    Raises:
        ValueError: An entry is not a four-number window.
    """
    hours: dict[int, Window] = {}
    for weekday, window in (raw or {}).items():
        if not (isinstance(window, (list, tuple)) and len(window) == 4):
            raise ValueError(f"calendars.yaml: hours for {key}, weekday {weekday} must be [start_h, start_m, end_h, end_m]")
        hours[int(weekday)] = tuple(window)  # type: ignore[assignment]
    return hours


class ConfiguredBooking:
    """Booking rules of a calendar declared in ``calendars.yaml``.

    Attributes:
        EVENT_TITLE_PREFIX: Start of the event title, and of the e-mail subject.
        TITLE_SEPARATOR: Separator between title parts.
        EMAIL_SUBJECT_PREFIX: Start of the notification e-mail subject.
        EMAIL_TEMPLATE_NAME: Template of the team notification e-mail.
    """

    TITLE_SEPARATOR = booking.TITLE_SEPARATOR

    def __init__(self, key: str, rules: Mapping[str, Any]) -> None:
        """Builds the rules.

        Args:
            key: Calendar key; the default title prefix.
            rules: Merged ``default`` + calendar entry.
        """
        self.EVENT_TITLE_PREFIX: str = rules.get("event_title_prefix") or key
        self.EMAIL_SUBJECT_PREFIX: str = rules.get("email_subject_prefix") or self.EVENT_TITLE_PREFIX
        self.EMAIL_TEMPLATE_NAME: str = rules.get("email_template_name") or booking.EMAIL_TEMPLATE_NAME
        self._hours = _plain_hours(key, rules.get("hours") or {})

    # The date helpers do not depend on the calendar.
    parse_start_date = staticmethod(booking.parse_start_date)
    parse_duration_minutes = staticmethod(booking.parse_duration_minutes)
    compute_end_date = staticmethod(booking.compute_end_date)
    is_future = staticmethod(booking.is_future)
    format_contact_name = staticmethod(booking.format_contact_name)

    def is_valid_business_hour(self, weekday: int, hour: int, minute: int) -> bool:
        """Tells whether a booking may start at this time.

        Args:
            weekday: 0 = Sunday ... 6 = Saturday.
            hour: Hour, 0-23.
            minute: Minute, 0-59.

        Returns:
            True when the weekday is open and the time is inside its window
            (the end is inclusive at the exact minute).
        """
        window = self._hours.get(weekday)
        if not window:
            return False
        start_h, start_m, end_h, end_m = window
        return (start_h, start_m) <= (hour, minute) <= (end_h, end_m)


class ConfiguredSlots:
    """Slot rules of a calendar declared in ``calendars.yaml``."""

    def __init__(self, key: str, rules: Mapping[str, Any]) -> None:
        """Builds the rules.

        Args:
            key: Calendar key, for error messages.
            rules: Merged ``default`` + calendar entry.
        """
        self._hours = _plain_hours(key, rules.get("hours") or {})
        lunch = rules.get("lunch_break") or {}
        self._lunch = (lunch.get("start_hour", 12), lunch.get("end_hour", 13)) if lunch else None

    def window(self, weekday: int, day: int) -> Optional[Window]:
        """Returns the opening window of a weekday.

        Args:
            weekday: 0 = Sunday ... 6 = Saturday.
            day: Day of the month (unused: configured calendars have no per-week rules).

        Returns:
            ``(start_hour, start_minute, end_hour, end_minute)``, or None when closed.
        """
        return self._hours.get(weekday)

    def is_lunch(self, slot_start: Any, slot_end: Any) -> bool:
        """Tells whether a slot overlaps the lunch break.

        Args:
            slot_start: Slot start in business time.
            slot_end: Slot end in business time.

        Returns:
            True when the slot must be excluded: it starts before the break ends and ends after it starts.
            A break without duration excludes nothing.
        """
        if self._lunch is None:
            return False
        lunch_start, lunch_end = self._lunch[0] * 60, self._lunch[1] * 60
        start_min = slot_start.hour * 60 + slot_start.minute
        end_min = slot_end.hour * 60 + slot_end.minute
        return lunch_start < lunch_end and start_min < lunch_end and end_min > lunch_start

    is_holiday = staticmethod(slot_calculator.is_holiday)

    _window = window
    _is_lunch = is_lunch

    def compute_available_slots(self, **kwargs: Any) -> List[Slot]:
        """Generates the bookable slots with this calendar's hours.

        Args:
            **kwargs: Same arguments as ``slot_calculator.compute_available_slots``
                (``now``, ``date_range_days``, ``duration_minutes``, ``interval_minutes``,
                ``user_tz``, ``busy_events``).

        Returns:
            The free slots.
        """
        return slot_calculator.compute_available_slots(window_fn=self._window, lunch_fn=self._is_lunch, **kwargs)


class FtHours:
    """Opening hours of the FT calendar: ``config/slots.yaml``."""

    window = staticmethod(slot_calculator.get_day_window_hours)
    is_lunch = staticmethod(slot_calculator.is_lunch_break)
    is_holiday = staticmethod(slot_calculator.is_holiday)


@dataclass(frozen=True)
class CalendarContext:
    """Everything an endpoint needs to work with one calendar.

    Attributes:
        key: Upper-case calendar key, e.g. ``"FT"``.
        tool: Credentials, ids and timings.
        booking: Booking rules (business hours, titles, e-mail template).
        slots: Slot rules; exposes ``compute_available_slots``.
        hours: Opening hours for the GHL tools: ``window``, ``is_lunch``, ``is_holiday``.
    """

    key: str
    tool: CalendarSettings
    booking: Any
    slots: Any
    hours: Any


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
        calendar_type: Value from the request, any letter case. Required: empty or None resolves to nothing.
        config: ``calendars.yaml`` contents; defaults to the file on disk.

    Returns:
        The calendar's context, or None when no such calendar is declared.
    """
    key = (calendar_type or "").strip().upper()
    tool = settings.calendars.get(key)
    if tool is None:
        return None
    if key == BUILTIN_RULES_KEY:
        return CalendarContext(key, tool, booking, slot_calculator, FtHours())

    cfg = load_calendars_config() if config is None else config
    entries = {str(k).upper(): v for k, v in (cfg.get("calendars") or {}).items()}
    rules = {**(cfg.get("default") or {}), **(entries.get(key) or {})}
    slots = ConfiguredSlots(key, rules)
    return CalendarContext(key, tool, ConfiguredBooking(key, rules), slots, slots)


def unknown_calendar_message(settings: Any, calendar_type: Optional[str]) -> str:
    """Builds the error for a calendar that is not declared.

    Args:
        settings: Plugin settings.
        calendar_type: The value the caller sent.

    Returns:
        A message that lists the valid keys; says the value is required when it is empty.
    """
    valid = ", ".join(available_keys(settings))
    if not (calendar_type or "").strip():
        return f"calendar_type is required. Valid values: {valid}"
    return f"Unknown calendar_type '{calendar_type}'. Valid values: {valid}"
