from datetime import datetime, timedelta, timezone

from agent_backend.slot_filters import (
    conflicts_with_busy,
    drop_after,
    drop_before,
    drop_conflicting,
    parse_busy,
    thin_by_interval,
)

T = datetime(2027, 3, 3, 14, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return T + timedelta(minutes=minutes)


def test_busy_events_are_parsed_and_unreadable_or_cancelled_ones_skipped():
    events = [
        {"startTime": "2027-03-03T14:00:00Z", "endTime": "2027-03-03T14:30:00Z"},
        {"start": "2027-03-03T15:00:00", "end": "2027-03-03T15:30:00"},  # naive -> UTC
        {"startTime": "2027-03-03T16:00:00Z", "endTime": "2027-03-03T16:30:00Z", "status": "cancelled"},
        {"startTime": "garbage", "endTime": "2027-03-03T17:30:00Z"},
        {"startTime": "2027-03-03T18:00:00Z"},
    ]
    assert parse_busy(events) == [(at(0), at(30)), (at(60), at(90))]


def test_post_buffer_keeps_free_time_after_an_existing_appointment():
    busy = [(at(0), at(30))]  # an appointment 14:00-14:30
    starts = [at(30), at(35), at(40), at(60)]
    assert drop_conflicting(starts, 30, busy) == starts
    # 10 minutes after the appointment ends at 14:30: 14:30 and 14:35 are too close, 14:40 is the first free start.
    assert drop_conflicting(starts, 30, busy, post_buffer_minutes=10) == [at(40), at(60)]


def test_pre_buffer_keeps_free_time_before_an_existing_appointment():
    busy = [(at(60), at(90))]  # an appointment 15:00-15:30
    # A 30-minute slot at 14:30 ends exactly when the appointment starts; a 10-minute pre buffer rejects it.
    assert drop_conflicting([at(30)], 30, busy) == [at(30)]
    assert drop_conflicting([at(30)], 30, busy, pre_buffer_minutes=10) == []
    assert drop_conflicting([at(20)], 30, busy, pre_buffer_minutes=10) == [at(20)]


def test_each_existing_appointment_blocks_its_own_buffers():
    busy = [(at(0), at(30)), (at(60), at(90))]
    free = drop_conflicting([at(m) for m in range(0, 120, 10)], 10, busy, pre_buffer_minutes=5, post_buffer_minutes=10)
    assert free == [at(40), at(100), at(110)]


def test_touching_edges_do_not_conflict_without_buffers():
    assert conflicts_with_busy(at(30), at(60), [(at(0), at(30))]) is False
    assert conflicts_with_busy(at(29), at(60), [(at(0), at(30))]) is True


def test_min_notice_and_date_range_drop_slots_outside_the_window():
    starts = [at(0), at(60), at(120)]
    assert drop_before(starts, at(60)) == [at(60), at(120)]
    assert drop_after(starts, at(60)) == [at(0), at(60)]


def test_interval_zero_keeps_every_slot_sorted():
    starts = [at(30), at(0), at(60)]
    assert thin_by_interval(starts, 0) == [at(0), at(30), at(60)]


def test_interval_keeps_starts_at_least_that_far_apart():
    starts = [at(m) for m in (0, 30, 60, 90, 120)]
    assert thin_by_interval(starts, 60) == [at(0), at(60), at(120)]
    assert thin_by_interval(starts, 45) == [at(0), at(60), at(120)]


def test_interval_restarts_each_day():
    next_day = T + timedelta(days=1)
    starts = [T, T + timedelta(minutes=30), next_day, next_day + timedelta(minutes=30)]
    assert thin_by_interval(starts, 60) == [T, next_day]
