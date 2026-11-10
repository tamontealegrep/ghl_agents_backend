import pytest

from desk.services.slots_sur import closing_hour, day_window, lunch_break


def test_day_window_monday_is_shorter():
    assert day_window(1) == (7, 30, 14, 0)


@pytest.mark.parametrize("weekday", [2, 3, 4, 5])
def test_day_window_tuesday_to_friday(weekday):
    assert day_window(weekday) == (7, 30, 16, 0)


@pytest.mark.parametrize("weekday", [0, 6])
def test_day_window_closed_weekend(weekday):
    assert day_window(weekday) is None


def test_lunch_break_excludes_slot_inside_the_lunch_hour():
    assert lunch_break(12 * 60, 12 * 60 + 30) is True  # 12:00-12:30
    assert lunch_break(12 * 60 + 30, 13 * 60) is True  # 12:30-13:00


def test_lunch_break_excludes_slot_that_overlaps_the_start_of_lunch():
    assert lunch_break(11 * 60 + 20, 12 * 60 + 10) is True  # 11:20-12:10 overlaps 10 minutes
    assert lunch_break(11 * 60 + 59, 12 * 60 + 29) is True


def test_lunch_break_excludes_slot_that_overlaps_the_end_of_lunch():
    assert lunch_break(12 * 60 + 50, 13 * 60 + 20) is True  # 12:50-13:20


def test_lunch_break_allows_slot_that_ends_exactly_when_lunch_starts():
    assert lunch_break(11 * 60 + 20, 12 * 60) is False  # 11:20-12:00
    assert lunch_break(11 * 60 + 30, 12 * 60) is False


def test_lunch_break_allows_slot_that_starts_exactly_when_lunch_ends():
    assert lunch_break(13 * 60, 13 * 60 + 30) is False  # 13:00-13:30


def test_closing_hour_is_2pm_on_monday_16pm_otherwise():
    assert closing_hour(1) == (14, 0)
    for weekday in (2, 3, 4, 5):
        assert closing_hour(weekday) == (16, 0)
