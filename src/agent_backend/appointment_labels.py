"""English labels of a booked appointment; the agent translates them to the contact's language."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

TIME_FORMATS = ("12h", "24h")
DEFAULT_TIME_FORMAT = "12h"

# Fixed names, so the labels never depend on the language of the server.
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def appointment_labels(start: datetime, timezone: str, time_format: str | None = None) -> tuple[str, str]:
    """Returns the date and the time of an appointment, in English, in the contact's time zone.

    The agent translates them to the language it speaks and saves them in the contact. English names are used because
    the same tool serves agents in several languages and a model translates a weekday, a month or AM/PM reliably, while
    it cannot know the format of a language it was not given.

    The date looks like ``Tuesday, November 16, 2026``. The time follows ``time_format``: ``12h`` (the default)
    gives ``08:50 AM`` (``12:00 PM`` at noon, ``12:30 AM`` after midnight) and ``24h`` gives ``08:50`` or ``14:05``.
    Anything other than ``24h`` is read as ``12h``.

    Args:
        start: Start of the appointment; it must carry a time zone.
        timezone: IANA time zone of the contact.
        time_format: ``12h`` or ``24h``.

    Returns:
        ``(appointment_date, appointment_time)``.
    """
    local = start.astimezone(ZoneInfo(timezone))
    date_label = f"{_WEEKDAYS[local.weekday()]}, {_MONTHS[local.month - 1]} {local.day}, {local.year}"
    if (time_format or DEFAULT_TIME_FORMAT).strip().lower() == "24h":
        time_label = f"{local.hour:02d}:{local.minute:02d}"
    else:
        time_label = f"{local.hour % 12 or 12:02d}:{local.minute:02d} {'AM' if local.hour < 12 else 'PM'}"
    return date_label, time_label
