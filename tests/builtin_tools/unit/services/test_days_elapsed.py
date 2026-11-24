from datetime import date, timedelta

import pytest

from agent_backend.builtin_tools.services.days_elapsed import (
    check_days_elapsed,
    parse_days_threshold,
    parse_ymd_date,
)


def test_date_slash_format():
    """A YYYY/MM/DD date is parsed."""
    assert parse_ymd_date("2024/06/15") == date(2024, 6, 15)


def test_date_dash_format():
    """A YYYY-MM-DD date is parsed."""
    assert parse_ymd_date("2024-06-15") == date(2024, 6, 15)


@pytest.mark.parametrize("raw", ["", "2024/06", "2024/06/15/00", "24/06/15", "abc"])
def test_date_invalid_raises(raw):
    """An invalid date raises ValueError."""
    with pytest.raises(ValueError):
        parse_ymd_date(raw)


@pytest.mark.parametrize("raw,expected", [(365, 365), ("365", 365), (365.0, 365), ("500", 500)])
def test_threshold_valid(raw, expected):
    """Valid thresholds are parsed to integers."""
    assert parse_days_threshold(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", 0, -5, "0", "-10"])
def test_threshold_invalid_is_none(raw):
    """Invalid thresholds give None."""
    assert parse_days_threshold(raw) is None


def test_elapsed_true_at_or_past_threshold():
    """A date at or past the threshold is elapsed."""
    input_date = date(2024, 1, 1)
    today = date(2025, 1, 1)  # 366 dias (2024 es bisiesto)
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 365)
    assert elapsed is True
    assert days_elapsed == 366


def test_elapsed_false_under_threshold():
    """A date under the threshold is not elapsed."""
    input_date = date(2024, 6, 1)
    today = date(2025, 1, 1)  # 214 dias
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 365)
    assert elapsed is False
    assert days_elapsed == 214


def test_elapsed_exact_boundary():
    """Exactly the threshold counts as elapsed."""
    input_date = date(2024, 1, 1)
    today = input_date + timedelta(days=500)
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 500)
    assert elapsed is True
    assert days_elapsed == 500


def test_elapsed_long_threshold():
    """A 500-day threshold works like a short one."""
    input_date = date(2023, 1, 1)
    today = date(2024, 6, 1)  # bastante mas de 500 dias
    elapsed, days_elapsed = check_days_elapsed(input_date, today, 500)
    assert elapsed is True
    assert days_elapsed > 500
