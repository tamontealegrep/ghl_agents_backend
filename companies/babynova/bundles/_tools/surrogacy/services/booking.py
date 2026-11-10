"""
Module.

    Core booking helpers: parsing start/duration, contact-name formatting, and
    Colombia business-hours validation. This is distinct from the availability
    calculator (this one does attend Saturday, and Mon-Fri closes at 18:00).
    Pure logic — no HTTP/Google concerns here.
"""

import re

from agent_backend.booking_helpers import compute_end_date, format_contact_name, is_future, parse_start_date  # noqa: F401
from agent_backend.booking_helpers import parse_duration_minutes as _parse_duration_minutes


def parse_duration_minutes(raw: str | None, default: int = 10) -> int:
    """Reads a duration in minutes; 10 when it is missing or not positive."""
    return _parse_duration_minutes(raw, default)


_LEADING_INT_RE = re.compile(r"^\s*(-?\d+)")

# Public constants used by endpoints for consistent titles/subjects
EVENT_TITLE_PREFIX = "First Visit"
TITLE_SEPARATOR = " - "
EMAIL_SUBJECT_PREFIX = "First Visit"
EMAIL_TEMPLATE_NAME = "book_appointment"


def is_valid_business_hour(weekday: int, hour: int, minute: int) -> bool:
    """Validate Colombia business hours.

    Weekday uses project convention (0=Sunday ... 6=Saturday, see utils/timezones.py).
    Sunday closed; Mon-Fri 07:00-18:00; Saturday 08:00-13:00.
    """
    if weekday == 0:  # Sunday
        return False
    if weekday in (1, 2, 3, 4, 5):  # Monday to Friday
        if hour < 7:
            return False
        if hour > 18 or (hour == 18 and minute > 0):
            return False
        return True
    if weekday == 6:  # Saturday
        if hour < 8:
            return False
        if hour > 13 or (hour == 13 and minute > 0):
            return False
        return True
    return False
