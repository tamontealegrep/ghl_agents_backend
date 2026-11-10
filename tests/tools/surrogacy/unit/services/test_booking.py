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


def test_parse_start_date_assumes_bogota_when_no_offset():
    dt = parse_start_date("2026-08-28T09:00:00")
    assert dt.isoformat() == "2026-08-28T09:00:00-05:00"


def test_parse_start_date_keeps_explicit_offset():
    dt = parse_start_date("2026-08-28T09:00:00-04:00")
    assert dt.isoformat() == "2026-08-28T09:00:00-04:00"


def test_parse_duration_minutes_default_is_10():
    assert parse_duration_minutes(None) == 10
    assert parse_duration_minutes("") == 10
    assert parse_duration_minutes("abc") == 10


def test_parse_duration_minutes_parses_leading_int():
    assert parse_duration_minutes("15") == 15
    assert parse_duration_minutes("20min") == 20


def test_parse_duration_minutes_non_positive_falls_back_to_default():
    assert parse_duration_minutes("0") == 10
    assert parse_duration_minutes("-5") == 10


def test_compute_end_date_adds_minutes():
    start = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
    end = compute_end_date(start, 10)
    assert end.isoformat() == "2026-08-28T09:10:00+00:00"


def test_is_future():
    now = datetime(2026, 8, 28, 9, 0, tzinfo=UTC)
    assert is_future(datetime(2026, 8, 28, 10, 0, tzinfo=UTC), now) is True
    assert is_future(datetime(2026, 8, 28, 8, 0, tzinfo=UTC), now) is False


def test_format_contact_name_trims_collapses_and_capitalizes():
    assert format_contact_name("  ana   maria   GOMEZ  ") == "Ana Maria Gomez"


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_weekday_valid_at_opening_and_closing(weekday):
    assert is_valid_business_hour(weekday, 7, 0) is True
    assert is_valid_business_hour(weekday, 18, 0) is True


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_weekday_invalid_before_opening_and_after_closing(weekday):
    assert is_valid_business_hour(weekday, 6, 59) is False
    assert is_valid_business_hour(weekday, 18, 1) is False


def test_saturday_valid_at_opening_and_closing():
    assert is_valid_business_hour(6, 8, 0) is True
    assert is_valid_business_hour(6, 13, 0) is True


def test_saturday_invalid_before_opening_and_after_closing():
    assert is_valid_business_hour(6, 7, 59) is False
    assert is_valid_business_hour(6, 13, 1) is False


def test_sunday_always_invalid():
    assert is_valid_business_hour(0, 10, 0) is False
