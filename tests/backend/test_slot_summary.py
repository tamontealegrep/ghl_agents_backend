"""Slot summary by day: the days, parts of the day and typed time blocks the voice agent says."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from agent_backend.slot_summary import summarize_days

BOGOTA = ZoneInfo("America/Bogota")


def _starts(day: str, times: list[str]) -> list[str]:
    return [f"{day}T{t}:00-05:00" for t in times]


def _bogota_window(day: str, first: str, last: str, step: int = 10) -> list[datetime]:
    """Slot starts, in Bogota time, from ``first`` to ``last`` (both included) every ``step`` minutes."""
    moment = datetime.fromisoformat(f"{day}T{first}:00").replace(tzinfo=BOGOTA)
    end = datetime.fromisoformat(f"{day}T{last}:00").replace(tzinfo=BOGOTA)
    out = []
    while moment <= end:
        out.append(moment)
        moment += timedelta(minutes=step)
    return out


def _in_zone(starts: list[datetime], zone: str) -> list[str]:
    """The same instants as ``start_local`` strings of the contact's zone."""
    return [s.astimezone(ZoneInfo(zone)).isoformat() for s in starts]


def test_consecutive_slots_form_a_continuous_range_and_isolated_ones_a_single_slot():
    """Consecutive slots become one continuous_range; an isolated slot stays a single_slot."""
    slots = _starts("2026-11-27", ["14:00", "14:10", "14:20", "15:00"])
    [day] = summarize_days(slots, "America/Bogota")
    assert day["date"] == "2026-11-27"
    assert day["label"] == "Friday, November 27"
    assert day["timezone"] == "America/Bogota"
    assert day["utc_offset"] == "-05:00"
    assert day["times"] == [
        {"type": "continuous_range", "first_start": "14:00", "last_start": "14:20", "every_minutes": 10},
        {"type": "single_slot", "start": "15:00"},
    ]
    assert day["parts_of_day"] == ["afternoon"]
    assert day["slot_count"] == 4


def test_one_entry_per_day_in_order_with_parts_of_the_day():
    """Days come soonest first and list every part of the day that has slots."""
    slots = _starts("2026-12-02", ["07:00", "07:10", "12:00", "12:10"]) + _starts("2026-11-30", ["08:00", "08:10"])
    days = summarize_days(slots, "America/Bogota")
    assert [d["date"] for d in days] == ["2026-11-30", "2026-12-02"]
    assert days[1]["parts_of_day"] == ["morning", "afternoon"]


def test_evening_and_night_parts():
    """18:00-21:00 is evening and 21:00-06:00 is night."""
    [day] = summarize_days(_starts("2026-11-27", ["18:00", "22:00"]), "America/Bogota")
    assert day["parts_of_day"] == ["evening", "night"]


def test_no_slots_gives_no_days():
    """Without slots there are no days."""
    assert summarize_days([], "America/Bogota") == []


def test_days_are_the_contacts_local_days_not_the_companys():
    """Friday afternoon in Bogota is Saturday morning in Tokyo: the contact hears Saturday."""
    local = _in_zone(_bogota_window("2026-11-27", "14:00", "16:30"), "Asia/Tokyo")
    [day] = summarize_days(local, "Asia/Tokyo")
    assert day["date"] == "2026-11-28"
    assert day["label"] == "Saturday, November 28"
    assert day["timezone"] == "Asia/Tokyo"
    assert day["utc_offset"] == "+09:00"
    assert day["times"] == [
        {"type": "continuous_range", "first_start": "04:00", "last_start": "06:30", "every_minutes": 10}
    ]
    assert day["parts_of_day"] == ["morning", "night"]


def test_a_block_that_crosses_local_midnight_is_split_in_two_days():
    """Monday 07:00-11:30 in Bogota is Monday 21:00 to Tuesday 01:30 in Tokyo: two local days."""
    local = _in_zone(_bogota_window("2026-11-30", "07:00", "11:30"), "Asia/Tokyo")
    days = summarize_days(local, "Asia/Tokyo")
    assert [d["date"] for d in days] == ["2026-11-30", "2026-12-01"]
    assert days[0]["times"] == [
        {"type": "continuous_range", "first_start": "21:00", "last_start": "23:50", "every_minutes": 10}
    ]
    assert days[1]["times"] == [
        {"type": "continuous_range", "first_start": "00:00", "last_start": "01:30", "every_minutes": 10}
    ]
    assert sum(d["slot_count"] for d in days) == 28


def test_europe_madrid_shifts_the_times_by_six_hours():
    """Bogota is UTC-5 and Madrid UTC+1 in winter: the same slots, six hours later, same day."""
    local = _in_zone(_bogota_window("2026-11-30", "07:00", "11:30"), "Europe/Madrid")
    [day] = summarize_days(local, "Europe/Madrid")
    assert day["date"] == "2026-11-30"
    assert day["utc_offset"] == "+01:00"
    assert day["times"] == [
        {"type": "continuous_range", "first_start": "13:00", "last_start": "17:30", "every_minutes": 10}
    ]
    assert day["parts_of_day"] == ["afternoon"]


def test_los_angeles_is_behind_bogota_and_keeps_the_day():
    """Los Angeles is UTC-8 in winter: three hours earlier than Bogota."""
    local = _in_zone(_bogota_window("2026-11-27", "14:00", "16:30"), "America/Los_Angeles")
    [day] = summarize_days(local, "America/Los_Angeles")
    assert day["utc_offset"] == "-08:00"
    assert day["times"][0]["first_start"] == "11:00"
    assert day["times"][0]["last_start"] == "13:30"
    assert day["parts_of_day"] == ["morning", "afternoon"]


def test_half_hour_offsets_keep_the_range():
    """India is UTC+5:30: Friday 14:00 in Bogota is Saturday 00:30 there, and the range is still continuous."""
    local = _in_zone(_bogota_window("2026-11-27", "14:00", "16:30"), "Asia/Kolkata")
    [day] = summarize_days(local, "Asia/Kolkata")
    assert day["utc_offset"] == "+05:30"
    assert day["date"] == "2026-11-28"
    assert day["times"] == [
        {"type": "continuous_range", "first_start": "00:30", "last_start": "03:00", "every_minutes": 10}
    ]


def test_daylight_saving_change_is_reflected_per_day():
    """Madrid changes offset on 2027-03-28: the days before and after report their own offset."""
    before = _in_zone(_bogota_window("2027-03-26", "07:00", "07:20"), "Europe/Madrid")
    after = _in_zone(_bogota_window("2027-03-29", "07:00", "07:20"), "Europe/Madrid")
    days = summarize_days(before + after, "Europe/Madrid")
    offsets = {d["date"]: d["utc_offset"] for d in days}
    assert offsets["2027-03-26"] == "+01:00"
    assert offsets["2027-03-29"] == "+02:00"


@pytest.mark.parametrize("zone", ["Asia/Tokyo", "Europe/Madrid", "America/Los_Angeles", "Asia/Kolkata", "America/Bogota"])
def test_every_slot_is_counted_exactly_once_in_any_zone(zone):
    """No slot is lost or duplicated when the days are the contact's local days."""
    starts = _bogota_window("2026-12-02", "07:00", "12:30") + _bogota_window("2026-12-04", "14:00", "16:30")
    days = summarize_days(_in_zone(starts, zone), zone)
    assert sum(d["slot_count"] for d in days) == len(starts)
