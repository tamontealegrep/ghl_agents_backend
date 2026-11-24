import pytest
from desk.services.slots_sur import closing_hour, day_window, lunch_break


def test_day_window_monday_is_shorter():
    """SUR's Monday window is shorter."""
    assert day_window(1) == (7, 30, 14, 0)


@pytest.mark.parametrize("weekday", [2, 3, 4, 5])
def test_day_window_tuesday_to_friday(weekday):
    """SUR is open Tuesday to Friday, 07:30 to 16:00."""
    assert day_window(weekday) == (7, 30, 16, 0)


@pytest.mark.parametrize("weekday", [0, 6])
def test_day_window_closed_weekend(weekday):
    """SUR is closed on weekends."""
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


def test_closing_hour_monday_2pm():
    """SUR closes at 2 pm on Monday and at 4 pm otherwise."""
    assert closing_hour(1) == (14, 0)
    for weekday in (2, 3, 4, 5):
        assert closing_hour(weekday) == (16, 0)
