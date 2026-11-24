import pytest
from desk.services.slots_ivf import closing_hour, day_window, lunch_break


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_day_window_open_monday_to_friday(weekday):
    """IVF is open Monday to Friday, 07:30 to 17:00."""
    assert day_window(weekday) == (7, 30, 17, 0)


@pytest.mark.parametrize("weekday", [0, 6])
def test_day_window_closed_weekend(weekday):
    """IVF is closed on weekends."""
    assert day_window(weekday) is None


def test_lunch_excludes_slot_inside():
    """A slot inside the lunch hour is excluded."""
    assert lunch_break(12 * 60, 12 * 60 + 30) is True  # 12:00-12:30
    assert lunch_break(12 * 60 + 30, 13 * 60) is True  # 12:30-13:00


def test_lunch_excludes_overlap_start():
    """A slot overlapping the start of lunch is excluded."""
    assert lunch_break(11 * 60 + 20, 12 * 60 + 10) is True  # 11:20-12:10 overlaps 10 minutes
    assert lunch_break(11 * 60 + 59, 12 * 60 + 29) is True


def test_lunch_excludes_overlap_end():
    """A slot overlapping the end of lunch is excluded."""
    assert lunch_break(12 * 60 + 50, 13 * 60 + 20) is True  # 12:50-13:20


def test_lunch_allows_slot_ending_at_start():
    """A slot ending exactly when lunch starts is allowed."""
    assert lunch_break(11 * 60 + 20, 12 * 60) is False  # 11:20-12:00
    assert lunch_break(11 * 60 + 30, 12 * 60) is False


def test_lunch_allows_slot_starting_at_end():
    """A slot starting exactly when lunch ends is allowed."""
    assert lunch_break(13 * 60, 13 * 60 + 30) is False  # 13:00-13:30


def test_closing_hour_is_always_5pm():
    """The closing hour is always 5 pm."""
    for weekday in range(7):
        assert closing_hour(weekday) == (17, 0)
