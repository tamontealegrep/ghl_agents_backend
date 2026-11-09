import pytest

from family_aims.services.slots_ivf import closing_hour, day_window, lunch_break


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_day_window_open_monday_to_friday(weekday):
    assert day_window(weekday) == (7, 0, 17, 0)


@pytest.mark.parametrize("weekday", [0, 6])
def test_day_window_closed_weekend(weekday):
    assert day_window(weekday) is None


def test_lunch_break_excludes_slot_starting_in_noon_hour():
    assert lunch_break(12 * 60, 12 * 60 + 30) is True  # 12:00-12:30
    assert lunch_break(12 * 60 + 30, 13 * 60) is True  # 12:30-13:00


def test_lunch_break_allows_slot_starting_before_noon():
    assert lunch_break(11 * 60 + 30, 12 * 60) is False  # 11:30-12:00


def test_lunch_break_allows_slot_starting_at_1pm():
    assert lunch_break(13 * 60, 13 * 60 + 30) is False  # 13:00-13:30


def test_closing_hour_is_always_5pm():
    for weekday in range(7):
        assert closing_hour(weekday) == (17, 0)
