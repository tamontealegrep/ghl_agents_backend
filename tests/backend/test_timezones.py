from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agent_backend.timezones import (
    add_days,
    build_business_instant,
    format_iso_with_offset,
    get_date_in_tz,
    get_date_key_in_tz,
    get_hour_in_tz,
    get_weekday_in_tz,
    parse_iso,
)


def test_iso_converts_utc_to_timezone():
    """An ISO string is written with the target timezone's offset."""
    dt_utc = datetime(2026, 8, 26, 15, 0, tzinfo=ZoneInfo("UTC"))
    assert format_iso_with_offset(dt_utc, "America/Bogota") == "2026-08-26T10:00:00-05:00"


def test_date_key_crosses_midnight():
    # 2026-08-27 02:00 UTC is still 2026-08-26 21:00 in Bogota (UTC-5)
    """The date key follows the local date across midnight."""
    dt_utc = datetime(2026, 8, 27, 2, 0, tzinfo=ZoneInfo("UTC"))
    assert get_date_key_in_tz(dt_utc, "America/Bogota") == "2026-08-26"


@pytest.mark.parametrize(
    "day,expected_weekday",
    [
        (23, 0),  # Domingo 2026-08-23 -> Domingo=0
        (24, 1),  # Lunes -> Lunes=1
        (25, 2),  # Martes
        (26, 3),  # Miercoles
        (27, 4),  # Jueves
        (28, 5),  # Viernes
        (29, 6),  # Sabado -> Sabado=6
    ],
)
def test_weekday_matches_js_mapping(day, expected_weekday):
    """Weekdays follow the original JS numbering."""
    dt = build_business_instant(2026, 8, day, 12, 0, "America/Bogota")
    assert get_weekday_in_tz(dt, "America/Bogota") == expected_weekday


def test_business_instant_has_offset():
    """A business instant is timezone-aware with the requested offset."""
    dt = build_business_instant(2026, 8, 26, 7, 0, "America/Bogota")
    assert dt.utcoffset() == timedelta(hours=-5)


def test_add_days_keeps_timezone():
    """Adding days keeps the timezone and advances the date."""
    dt = build_business_instant(2026, 8, 26, 7, 0, "America/Bogota")
    result = add_days(dt, 3)
    assert result.day == 29
    assert result.utcoffset() == timedelta(hours=-5)


def test_add_days_negative():
    """Adding negative days goes back in time."""
    dt = build_business_instant(2026, 8, 26, 7, 0, "America/Bogota")
    result = add_days(dt, -1)
    assert result.day == 25


def test_parse_iso_zulu():
    """An ISO string ending in Z is parsed as UTC."""
    dt = parse_iso("2026-08-26T15:00:00Z")
    assert dt == datetime(2026, 8, 26, 15, 0, tzinfo=ZoneInfo("UTC"))


def test_parse_iso_offset():
    """An ISO string with an explicit offset keeps it."""
    dt = parse_iso("2026-08-26T10:00:00-05:00")
    assert dt.utcoffset() == timedelta(hours=-5)


def test_hour_in_timezone():
    """The hour is returned in the local timezone."""
    dt_utc = datetime(2026, 8, 26, 15, 30, tzinfo=ZoneInfo("UTC"))
    assert get_hour_in_tz(dt_utc, "America/Bogota") == 10


def test_date_crosses_midnight():
    """The date follows the local date across midnight."""
    dt_utc = datetime(2026, 8, 27, 2, 0, tzinfo=ZoneInfo("UTC"))
    d = get_date_in_tz(dt_utc, "America/Bogota")
    assert d.isoformat() == "2026-08-26"
