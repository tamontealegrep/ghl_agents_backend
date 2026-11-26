"""Slot summary by day: the days, parts of the day and typed time blocks the voice agent says."""

from agent_backend.slot_summary import summarize_days


def _starts(day: str, times: list[str]) -> list[str]:
    return [f"{day}T{t}:00-05:00" for t in times]


def test_consecutive_slots_form_a_continuous_range_and_isolated_ones_a_single_slot():
    """Consecutive slots become one continuous_range; an isolated slot stays a single_slot."""
    slots = _starts("2026-11-27", ["14:00", "14:10", "14:20", "15:00"])
    [day] = summarize_days(slots)
    assert day["date"] == "2026-11-27"
    assert day["label"] == "Friday, November 27"
    assert day["times"] == [
        {"type": "continuous_range", "first_start": "14:00", "last_start": "14:20", "every_minutes": 10},
        {"type": "single_slot", "start": "15:00"},
    ]
    assert day["parts_of_day"] == ["afternoon"]
    assert day["slot_count"] == 4


def test_one_entry_per_day_in_order_with_parts_of_the_day():
    """Days come soonest first and list every part of the day that has slots."""
    slots = _starts("2026-12-02", ["07:00", "07:10", "12:00", "12:10"]) + _starts("2026-11-30", ["08:00", "08:10"])
    days = summarize_days(slots)
    assert [d["date"] for d in days] == ["2026-11-30", "2026-12-02"]
    assert days[1]["parts_of_day"] == ["morning", "afternoon"]


def test_evening_and_night_parts():
    """18:00-21:00 is evening and 21:00-06:00 is night."""
    [day] = summarize_days(_starts("2026-11-27", ["18:00", "22:00"]))
    assert day["parts_of_day"] == ["evening", "night"]


def test_no_slots_gives_no_days():
    """Without slots there are no days."""
    assert summarize_days([]) == []
