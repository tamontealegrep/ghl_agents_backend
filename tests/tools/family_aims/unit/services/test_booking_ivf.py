import pytest

from family_aims.services.booking_ivf import is_valid_business_hour


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_valid_at_opening_and_closing(weekday):
    assert is_valid_business_hour(weekday, 7, 0) is True
    assert is_valid_business_hour(weekday, 17, 0) is True


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_invalid_before_opening_and_after_closing(weekday):
    assert is_valid_business_hour(weekday, 6, 59) is False
    assert is_valid_business_hour(weekday, 17, 1) is False


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_lunch_hour_blocked_entirely(weekday):
    assert is_valid_business_hour(weekday, 12, 0) is False
    assert is_valid_business_hour(weekday, 12, 59) is False


def test_hour_right_after_lunch_is_valid():
    assert is_valid_business_hour(1, 13, 0) is True


@pytest.mark.parametrize("weekday", [0, 6])
def test_weekend_always_invalid(weekday):
    assert is_valid_business_hour(weekday, 10, 0) is False
