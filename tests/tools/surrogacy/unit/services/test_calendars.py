from datetime import UTC, datetime, timedelta

import pytest
from surrogacy.services import booking, slot_calculator
from surrogacy.services.calendars import (
    ConfiguredBooking,
    ConfiguredSlots,
    resolve_calendar,
)

from agent_backend.calendars import CalendarSettings


def _tool() -> CalendarSettings:
    return CalendarSettings("", "", "", "id", "")


class _Settings:
    calendars = {"FT": _tool(), "CONTROL": _tool()}


def test_ft_keeps_the_original_rules():
    cal = resolve_calendar(_Settings(), "ft")
    assert cal.booking is booking and cal.slots is slot_calculator


def test_missing_calendar_type_resolves_to_nothing_and_says_it_is_required():
    from surrogacy.services.calendars import unknown_calendar_message

    for missing in (None, "", "   "):
        assert resolve_calendar(_Settings(), missing) is None
        assert "calendar_type is required" in unknown_calendar_message(_Settings(), missing)
    assert resolve_calendar(_Settings(), "NOPE") is None
    assert "Unknown calendar_type 'NOPE'" in unknown_calendar_message(_Settings(), "NOPE")


def test_new_calendar_defaults_title_to_its_key_and_entry_overrides_it():
    config = {
        "default": {"hours": {1: [7, 0, 18, 0]}},
        "calendars": {"control": {"event_title_prefix": "Control"}},
    }
    assert resolve_calendar(_Settings(), "CONTROL", config).booking.EVENT_TITLE_PREFIX == "Control"
    assert (
        resolve_calendar(_Settings(), "CONTROL", {"default": {}, "calendars": {}}).booking.EVENT_TITLE_PREFIX
        == "CONTROL"
    )


def test_hours_that_are_not_four_numbers_fail_loudly():
    with pytest.raises(ValueError, match="CONTROL"):
        ConfiguredBooking("CONTROL", {"hours": {1: {"weeks": [1], "window": [8, 0, 12, 0]}}})


def test_configured_booking_matches_the_ft_rules_for_every_minute_of_the_week():
    hours = {d: [7, 0, 18, 0] for d in (1, 2, 3, 4, 5)} | {6: [8, 0, 13, 0]}
    configured = ConfiguredBooking("X", {"hours": hours})
    for weekday in range(7):
        for hour in range(24):
            for minute in (0, 1, 30, 59):
                assert configured.is_valid_business_hour(
                    weekday, hour, minute
                ) == booking.is_valid_business_hour(weekday, hour, minute), (weekday, hour, minute)


def test_configured_slots_match_the_ft_calculator_when_given_the_same_hours(monkeypatch):
    ft_hours = {1: [7, 0, 12, 0], 3: [7, 0, 13, 0], 5: [14, 0, 17, 0]}
    slots_yaml = {"holidays": [], "windows": ft_hours, "lunch_break": {"start_hour": 13, "end_hour": 13}}
    monkeypatch.setattr(slot_calculator, "load_slots_config", lambda: slots_yaml)
    now = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)
    kwargs = dict(
        now=now,
        date_range_days=14,
        duration_minutes=30,
        interval_minutes=35,
        user_tz="America/Bogota",
        busy_events=[],
    )

    expected = slot_calculator.compute_available_slots(**kwargs)
    configured = ConfiguredSlots("X", {"hours": ft_hours, "lunch_break": {"start_hour": 13, "end_hour": 13}})

    assert expected  # the comparison is not vacuous
    assert configured.compute_available_slots(**kwargs) == expected


def test_configured_slots_skip_the_lunch_break_and_closed_days():
    configured = ConfiguredSlots(
        "X", {"hours": {2: [8, 0, 14, 0]}, "lunch_break": {"start_hour": 12, "end_hour": 13}}
    )
    now = datetime(2027, 3, 1, 12, 0, tzinfo=UTC)
    slots = configured.compute_available_slots(
        now=now, date_range_days=14, duration_minutes=60, user_tz="America/Bogota", busy_events=[]
    )
    starts = [datetime.fromisoformat(s.start_co) for s in slots]
    assert starts and all(s.isoweekday() == 2 for s in starts)  # only Tuesdays
    assert all(s.hour != 12 for s in starts)
    assert any(s.hour == 8 for s in starts) and any(s.hour == 13 for s in starts)
    assert timedelta(hours=1) == datetime.fromisoformat(slots[0].end_co) - starts[0]
