from datetime import UTC, datetime

import pytest

from agent_backend.builtin_tools.services.time_now import get_calendar, get_current_time


def test_get_current_time_returns_iso_string_with_offset():
    result = get_current_time("America/Bogota")
    assert result.endswith("-05:00")


def test_get_current_time_utc_matches_wall_clock_within_a_few_seconds():
    result = get_current_time("UTC")
    parsed = datetime.fromisoformat(result)
    assert abs((datetime.now(UTC) - parsed).total_seconds()) < 5


def test_get_current_time_invalid_timezone_raises():
    with pytest.raises(Exception):
        get_current_time("No/Existe")


def test_get_calendar_lists_today_first_with_weekday_names():
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
