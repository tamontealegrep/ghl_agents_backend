"""Booking helpers that do not depend on the company: date parsing and contact-name formatting."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

__all__ = ["compute_end_date", "format_contact_name", "is_future", "parse_duration_minutes", "parse_start_date"]

_LEADING_INT_RE = re.compile(r"^\s*(-?\d+)")


def parse_start_date(start_date_str: str, default_tz: str = "America/Bogota") -> datetime:
    """Parses ``start_date`` to a timezone-aware datetime.

    Args:
        start_date_str: ISO 8601 text, with or without offset or ``Z``.
        default_tz: Timezone assumed when the text has no offset.

    Returns:
        The aware datetime.

    Raises:
        ValueError: The text is not a valid ISO 8601 date.
    """
    dt = datetime.fromisoformat(start_date_str.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=ZoneInfo(default_tz))


def parse_duration_minutes(raw: str | None, default: int) -> int:
    """Reads a duration like JavaScript's ``parseInt(x, 10) || default``, rejecting durations of 0 or less.

    Args:
        raw: Text such as ``"30"`` or ``"30 min"``; None is allowed.
        default: Value used when ``raw`` has no positive leading integer.

    Returns:
        The duration in minutes.
    """
    if raw is None:
        return default
    match = _LEADING_INT_RE.match(raw)
    if not match:
        return default
    value = int(match.group(1))
    return value if value > 0 else default


def compute_end_date(start_dt: datetime, duration_minutes: int) -> datetime:
    """Returns the end of an appointment.

    Args:
        start_dt: Start.
        duration_minutes: Length in minutes.

    Returns:
        ``start_dt`` plus the duration.
    """
    return start_dt + timedelta(minutes=duration_minutes)


def is_future(start_dt: datetime, now_utc: datetime) -> bool:
    """Tells whether a start is after ``now_utc``.

    Args:
        start_dt: Start.
        now_utc: Current time.

    Returns:
        True when ``start_dt`` is strictly later.
    """
    return start_dt > now_utc


def format_contact_name(raw_name: str) -> str:
    """Trims, collapses spaces and capitalizes each word.

    Args:
        raw_name: Name as typed.

    Returns:
        The tidied name.
    """
    return " ".join(word.capitalize() for word in raw_name.strip().split())
