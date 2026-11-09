from datetime import datetime
from zoneinfo import ZoneInfo

from family_aims.utils.timezones import (
    build_business_instant,
    format_iso_with_offset,
    get_date_in_tz,
    get_hour_in_tz,
    get_weekday_in_tz,
    parse_iso,
)


def test_format_iso_with_offset_converts_utc_to_target_timezone():
    dt_utc = datetime(2026, 8, 26, 15, 0, tzinfo=ZoneInfo("UTC"))
    assert format_iso_with_offset(dt_utc, "America/Bogota") == "2026-08-26T10:00:00-05:00"


def test_get_weekday_in_tz_matches_js_mapping():
    # 2026-08-26 es miercoles
    dt = build_business_instant(2026, 8, 26, 12, 0, "America/Bogota")
    assert get_weekday_in_tz(dt, "America/Bogota") == 3


def test_get_hour_in_tz_returns_local_hour():
    dt_utc = datetime(2026, 8, 26, 15, 30, tzinfo=ZoneInfo("UTC"))
    assert get_hour_in_tz(dt_utc, "America/Bogota") == 10


def test_get_date_in_tz_crosses_midnight_boundary():
    dt_utc = datetime(2026, 8, 27, 2, 0, tzinfo=ZoneInfo("UTC"))
    d = get_date_in_tz(dt_utc, "America/Bogota")
    assert d.isoformat() == "2026-08-26"


def test_build_business_instant_is_aware_with_requested_offset():
    dt = build_business_instant(2026, 8, 26, 7, 0, "America/Bogota")
    assert dt.utcoffset().total_seconds() == -5 * 3600


def test_parse_iso_accepts_zulu_suffix():
    dt = parse_iso("2026-08-26T15:00:00Z")
    assert dt == datetime(2026, 8, 26, 15, 0, tzinfo=ZoneInfo("UTC"))
