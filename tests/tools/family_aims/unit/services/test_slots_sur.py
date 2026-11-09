import pytest

from family_aims.services.slots_sur import closing_hour, day_window, lunch_break


def test_day_window_monday_is_shorter():
    assert day_window(1) == (7, 0, 14, 0)


@pytest.mark.parametrize("weekday", [2, 3, 4, 5])
def test_day_window_tuesday_to_friday(weekday):
    assert day_window(weekday) == (7, 0, 16, 0)


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


def test_closing_hour_is_2pm_on_monday_16pm_otherwise():
    assert closing_hour(1) == (14, 0)
    for weekday in (2, 3, 4, 5):
        assert closing_hour(weekday) == (16, 0)
