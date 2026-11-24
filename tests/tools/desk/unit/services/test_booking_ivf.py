import pytest
from desk.services.booking_ivf import is_valid_business_hour


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_valid_at_opening_and_closing(weekday):
    """IVF hours are valid at opening and closing time."""
    assert is_valid_business_hour(weekday, 7, 30) is True
    assert is_valid_business_hour(weekday, 17, 0) is True


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_invalid_before_opening_and_after_closing(weekday):
    """Times before opening or after closing are invalid."""
    assert is_valid_business_hour(weekday, 6, 59) is False
    assert is_valid_business_hour(weekday, 17, 1) is False


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_lunch_hour_blocked_entirely(weekday):
    """The whole lunch hour is blocked."""
    assert is_valid_business_hour(weekday, 12, 0) is False
    assert is_valid_business_hour(weekday, 12, 59) is False


def test_hour_right_after_lunch_is_valid():
    """The hour right after lunch is valid."""
    assert is_valid_business_hour(1, 13, 0) is True


@pytest.mark.parametrize("weekday", [0, 6])
def test_weekend_always_invalid(weekday):
    """Weekends are always invalid."""
    assert is_valid_business_hour(weekday, 10, 0) is False


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_invalid_before_0730(weekday):
    """Times before 07:30 are invalid."""
    assert is_valid_business_hour(weekday, 7, 0) is False
    assert is_valid_business_hour(weekday, 7, 29) is False
