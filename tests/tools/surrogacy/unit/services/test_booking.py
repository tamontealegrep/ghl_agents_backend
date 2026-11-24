from datetime import UTC, datetime

import pytest
from surrogacy.services.booking import (
    compute_end_date,
    format_contact_name,
    is_future,
    is_valid_business_hour,
    parse_duration_minutes,
    parse_start_date,
)


def test_start_date_defaults_to_bogota():
    """A start date without an offset is read as Bogota time."""
    dt = parse_start_date("2026-08-28T09:00:00")
    assert dt.isoformat() == "2026-08-28T09:00:00-05:00"


def test_start_date_keeps_offset():
    """A start date with an offset keeps it."""
    dt = parse_start_date("2026-08-28T09:00:00-04:00")
    assert dt.isoformat() == "2026-08-28T09:00:00-04:00"


def test_duration_default_is_10():
    """The default duration is 10 minutes."""
    assert parse_duration_minutes(None) == 10
    assert parse_duration_minutes("") == 10
    assert parse_duration_minutes("abc") == 10


def test_duration_parses_integer():
    """A numeric string is parsed to minutes."""
    assert parse_duration_minutes("15") == 15
    assert parse_duration_minutes("20min") == 20


def test_duration_non_positive_falls_back():
    """A non-positive duration falls back to the default."""
    assert parse_duration_minutes("0") == 10
    assert parse_duration_minutes("-5") == 10


def test_end_date_adds_minutes():
    """The end date is the start plus the duration."""
    start = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
    end = compute_end_date(start, 10)
    assert end.isoformat() == "2026-08-28T09:10:00+00:00"


def test_is_future():
    """A later date is in the future."""
    now = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
    assert is_future(datetime(2026, 8, 28, 10, 0, tzinfo=UTC), now) is True
    assert is_future(datetime(2026, 8, 28, 8, 0, tzinfo=UTC), now) is False


def test_contact_name_tidied():
    """Contact names are trimmed, collapsed and capitalised."""
    assert format_contact_name("  ana   maria   GOMEZ  ") == "Ana Maria Gomez"


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_weekday_valid_at_edges(weekday):
    """Weekday hours are valid at opening and closing time."""
    assert is_valid_business_hour(weekday, 7, 0) is True
    assert is_valid_business_hour(weekday, 18, 0) is True


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_weekday_invalid_outside_edges(weekday):
    """Weekday times before opening or after closing are invalid."""
    assert is_valid_business_hour(weekday, 6, 59) is False
    assert is_valid_business_hour(weekday, 18, 1) is False


def test_saturday_valid_at_edges():
    """Saturday hours are valid at opening and closing time."""
    assert is_valid_business_hour(6, 8, 0) is True
    assert is_valid_business_hour(6, 13, 0) is True


def test_saturday_invalid_outside_edges():
    """Saturday times before opening or after closing are invalid."""
    assert is_valid_business_hour(6, 7, 59) is False
    assert is_valid_business_hour(6, 13, 1) is False


def test_sunday_always_invalid():
    """Sundays are always invalid."""
    assert is_valid_business_hour(0, 10, 0) is False
