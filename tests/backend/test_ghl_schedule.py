import asyncio

import pytest

from agent_backend.calendars import CalendarSettings, load_calendar_settings
from agent_backend.ghl_schedule import clear_cache, resolve_schedule, schedule_from_calendar, to_days, to_minutes

# The settings of the real FT calendar, as returned by GHL's Get Calendar.
GHL_CALENDAR = {
    "slotDuration": 30,
    "slotDurationUnit": "mins",
    "slotInterval": 10,
    "slotIntervalUnit": "mins",
    "preBuffer": None,
    "preBufferUnit": "mins",
    "slotBuffer": 15,
    "slotBufferUnit": "mins",
    "allowBookingAfter": 0,
    "allowBookingAfterUnit": "days",
    "allowBookingFor": 14,
    "allowBookingForUnit": "days",
}


def tool(**env) -> CalendarSettings:
    env = {f"BN_{k}_FT": v for k, v in env.items()}
    return load_calendar_settings("BN", "FT", read_unset_from_ghl=True, environ={"BN_GHL_CALENDAR_ID_FT": "cal1", **env})


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()


def test_units_are_converted_to_minutes_and_days():
    assert to_minutes(15, "mins") == 15
    assert to_minutes(2, "hours") == 120
    assert to_minutes(1, "days") == 1440
    assert to_minutes(1, None) == 1
    assert to_minutes(None, "mins") is None and to_minutes(5, "fortnights") is None
    assert to_days(2, "weeks") == 14 and to_days(1, "months") == 30 and to_days(36, "hours") == 2 and to_days(0, "days") == 0


def test_empty_variables_take_their_value_from_the_ghl_calendar():
    schedule = schedule_from_calendar(GHL_CALENDAR, tool())
    assert (schedule.duration_minutes, schedule.pre_buffer_minutes, schedule.post_buffer_minutes) == (30, 0, 15)
    assert (schedule.min_notice_minutes, schedule.date_range_days) == (0, 14)
    assert schedule.from_ghl == {"duration_minutes", "pre_buffer_minutes", "post_buffer_minutes", "min_notice_minutes", "date_range_days"}


def test_a_value_in_the_env_wins_over_ghl():
    schedule = schedule_from_calendar(GHL_CALENDAR, tool(POST_BUFFER_MINUTES="20", DURATION_MINUTES="45"))
    assert (schedule.duration_minutes, schedule.post_buffer_minutes) == (45, 20)
    assert "post_buffer_minutes" not in schedule.from_ghl and "duration_minutes" not in schedule.from_ghl
    assert schedule.pre_buffer_minutes == 0  # still from GHL


def test_interval_is_never_taken_from_ghl():
    assert schedule_from_calendar(GHL_CALENDAR, tool()).interval_minutes == 0


def test_a_booking_window_of_zero_means_no_limit_and_keeps_the_fallback():
    schedule = schedule_from_calendar({**GHL_CALENDAR, "allowBookingFor": 0}, tool())
    assert schedule.date_range_days == 14 and "date_range_days" not in schedule.from_ghl


def test_min_notice_can_be_hours_days_or_weeks():
    assert schedule_from_calendar({**GHL_CALENDAR, "allowBookingAfter": 2, "allowBookingAfterUnit": "hours"}, tool()).min_notice_minutes == 120
    assert schedule_from_calendar({**GHL_CALENDAR, "allowBookingAfter": 1, "allowBookingAfterUnit": "weeks"}, tool()).min_notice_minutes == 10080


def test_without_empty_variables_ghl_is_not_even_called():
    calls = []

    async def fetch(*args):
        calls.append(args)
        return {"calendar": GHL_CALENDAR}

    fixed = load_calendar_settings("BN", "FT", environ={"BN_GHL_CALENDAR_ID_FT": "c"})  # nothing marked for GHL
    schedule = asyncio.run(resolve_schedule(fixed, "token", get_calendar=fetch))
    assert calls == [] and schedule.post_buffer_minutes == 0


def test_the_ghl_calendar_is_read_once_and_cached():
    calls = []

    async def fetch(token, calendar_id):
        calls.append(calendar_id)
        return {"calendar": GHL_CALENDAR}

    for _ in range(3):
        schedule = asyncio.run(resolve_schedule(tool(), "token", get_calendar=fetch))
    assert calls == ["cal1"] and schedule.post_buffer_minutes == 15


def test_if_ghl_cannot_be_read_the_defaults_are_used():
    async def fetch(*args):
        raise RuntimeError("down")

    schedule = asyncio.run(resolve_schedule(tool(), "token", get_calendar=fetch))
    assert (schedule.duration_minutes, schedule.post_buffer_minutes, schedule.date_range_days) == (30, 0, 14)
    assert schedule.from_ghl == frozenset()
