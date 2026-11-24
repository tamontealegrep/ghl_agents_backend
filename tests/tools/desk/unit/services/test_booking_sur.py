import pytest
from desk.services.booking_sur import is_valid_business_hour


def test_monday_valid_at_opening_and_closing():
    """Monday hours are valid at opening and closing time."""
    assert is_valid_business_hour(1, 7, 30) is True
    assert is_valid_business_hour(1, 14, 0) is True


def test_monday_invalid_after_1400():
    """Monday after 14:00 is invalid."""
    assert is_valid_business_hour(1, 14, 1) is False
    assert is_valid_business_hour(1, 15, 0) is False


@pytest.mark.parametrize("weekday", [2, 3, 4, 5])
def test_tue_to_fri_valid_at_edges(weekday):
    """Tuesday to Friday hours are valid at opening and closing time."""
    assert is_valid_business_hour(weekday, 7, 30) is True
    assert is_valid_business_hour(weekday, 16, 0) is True


@pytest.mark.parametrize("weekday", [2, 3, 4, 5])
def test_tue_to_fri_invalid_after_1600(weekday):
    """Tuesday to Friday after 16:00 is invalid."""
    assert is_valid_business_hour(weekday, 16, 1) is False
    assert is_valid_business_hour(weekday, 17, 0) is False


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_lunch_hour_blocked_entirely(weekday):
    """The whole lunch hour is blocked."""
    assert is_valid_business_hour(weekday, 12, 0) is False
    assert is_valid_business_hour(weekday, 12, 59) is False


@pytest.mark.parametrize("weekday", [0, 6])
def test_weekend_always_invalid(weekday):
    """Weekends are always invalid."""
    assert is_valid_business_hour(weekday, 10, 0) is False


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_invalid_before_0730(weekday):
    """Times before 07:30 are invalid."""
    assert is_valid_business_hour(weekday, 7, 0) is False
    assert is_valid_business_hour(weekday, 7, 29) is False
