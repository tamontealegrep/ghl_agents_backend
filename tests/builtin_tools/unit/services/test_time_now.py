from datetime import UTC, datetime

import pytest

from agent_backend.builtin_tools.services.time_now import get_calendar, get_current_time


def test_time_is_iso_with_offset():
    """The current time is an ISO string with the timezone offset."""
    result = get_current_time("America/Bogota")
    assert result.endswith("-05:00")


def test_time_utc_matches_clock():
    """The UTC time matches the clock within a few seconds."""
    result = get_current_time("UTC")
    parsed = datetime.fromisoformat(result)
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 5


def test_time_invalid_timezone_raises():
    """An invalid timezone raises an exception."""
    with pytest.raises(Exception):
        get_current_time("No/Existe")


def test_calendar_today_first():
    """The calendar lists today first, with weekday names."""
    entries = get_calendar("America/Bogota", days=7).split(", ")
    assert len(entries) == 7
    assert entries[0].split(" ")[0] <= entries[1].split(" ")[0]
    assert entries[0].split(" ")[1] in {
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    }
