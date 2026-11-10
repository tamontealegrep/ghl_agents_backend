from datetime import date, timedelta

import pytest

from agent_backend.builtin_tools.services.days_elapsed import (
    check_days_elapsed,
    parse_days_threshold,
    parse_ymd_date,
)


def test_parse_ymd_date_valid():
    assert parse_ymd_date("2024/06/15") == date(2024, 6, 15)


def test_parse_ymd_date_accepts_dash_format():
    assert parse_ymd_date("2024-06-15") == date(2024, 6, 15)


@pytest.mark.parametrize("raw", ["", "2024/06", "2024/06/15/00", "24/06/15", "abc"])
def test_parse_ymd_date_invalid_raises(raw):
    with pytest.raises(ValueError):
        parse_ymd_date(raw)


@pytest.mark.parametrize("raw,expected", [(365, 365), ("365", 365), (365.0, 365), ("500", 500)])
def test_parse_days_threshold_valid(raw, expected):
    assert parse_days_threshold(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", 0, -5, "0", "-10"])
def test_parse_days_threshold_invalid_returns_none(raw):
    assert parse_days_threshold(raw) is None


def test_check_days_elapsed_true_when_at_or_past_threshold():
    input_date = date(2024, 1, 1)
    today = date(2025, 1, 1)  # 366 dias (2024 es bisiesto)
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 365)
    assert elapsed is True
    assert days_elapsed == 366


def test_check_days_elapsed_false_when_under_threshold():
    input_date = date(2024, 6, 1)
    today = date(2025, 1, 1)  # 214 dias
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 365)
    assert elapsed is False
    assert days_elapsed == 214


def test_check_days_elapsed_exact_boundary_counts_as_elapsed():
    input_date = date(2024, 1, 1)
    today = input_date + timedelta(days=500)
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 500)
    assert elapsed is True
    assert days_elapsed == 500


def test_check_days_elapsed_supports_500_day_threshold():
    input_date = date(2023, 1, 1)
    today = date(2024, 6, 1)  # bastante mas de 500 dias
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 500)
    assert elapsed is True
    assert days_elapsed > 500
