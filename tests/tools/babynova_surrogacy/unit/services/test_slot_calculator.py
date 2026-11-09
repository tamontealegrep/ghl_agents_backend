from datetime import timedelta

import pytest

from babynova_surrogacy.services.slot_calculator import (
    compute_available_slots,
    compute_processing_day_key,
    get_candidate_days_list,
    get_day_window_hours,
    is_holiday,
    valid_advance,
)
from babynova_surrogacy.utils.timezones import build_business_instant

BOGOTA = "America/Bogota"


# ---------------------------------------------------------------------------
# get_day_window_hours
# ---------------------------------------------------------------------------

def test_get_day_window_hours_monday():
    assert get_day_window_hours(1, 10) == (7, 0, 12, 0)


def test_get_day_window_hours_wednesday():
    assert get_day_window_hours(3, 10) == (7, 0, 13, 0)


def test_get_day_window_hours_friday():
    assert get_day_window_hours(5, 10) == (14, 0, 17, 0)


def test_get_day_window_hours_first_saturday_of_month():
    assert get_day_window_hours(6, 7) == (8, 0, 12, 0)


def test_get_day_window_hours_saturday_after_first_week_is_closed():
    assert get_day_window_hours(6, 8) is None


@pytest.mark.parametrize("weekday", [0, 2, 4])
def test_get_day_window_hours_closed_on_other_days(weekday):
    assert get_day_window_hours(weekday, 15) is None


# ---------------------------------------------------------------------------
# is_holiday
# ---------------------------------------------------------------------------

def test_is_holiday_known_date():
    assert is_holiday(2026, 1, 1) is True


def test_is_holiday_regular_date():
    assert is_holiday(2026, 8, 26) is False


# ---------------------------------------------------------------------------
# compute_processing_day_key
# ---------------------------------------------------------------------------

def test_compute_processing_day_key_regular_weekday():
    # Miercoles 2026-08-26 -> siguiente dia es jueves, sin salto
    now = build_business_instant(2026, 8, 26, 12, 0, BOGOTA)
    assert compute_processing_day_key(now) == "2026-08-27"


def test_compute_processing_day_key_skips_saturday_to_monday():
    # Viernes 2026-08-28 -> siguiente dia es sabado -> salta a lunes
    now = build_business_instant(2026, 8, 28, 12, 0, BOGOTA)
    assert compute_processing_day_key(now) == "2026-08-31"


def test_compute_processing_day_key_skips_sunday_to_monday():
    # Sabado 2026-08-29 -> siguiente dia es domingo -> salta a lunes
    now = build_business_instant(2026, 8, 29, 12, 0, BOGOTA)
    assert compute_processing_day_key(now) == "2026-08-31"


# ---------------------------------------------------------------------------
# valid_advance
# ---------------------------------------------------------------------------

def test_valid_advance_true_when_slot_day_after_processing_day():
    slot_start = build_business_instant(2026, 8, 28, 7, 0, BOGOTA)
    assert valid_advance(slot_start, "2026-08-27") is True


def test_valid_advance_false_when_slot_day_equals_processing_day():
    slot_start = build_business_instant(2026, 8, 27, 7, 0, BOGOTA)
    assert valid_advance(slot_start, "2026-08-27") is False


def test_valid_advance_false_when_slot_day_before_processing_day():
    slot_start = build_business_instant(2026, 8, 26, 7, 0, BOGOTA)
    assert valid_advance(slot_start, "2026-08-27") is False


# ---------------------------------------------------------------------------
# get_candidate_days_list
# ---------------------------------------------------------------------------

def test_get_candidate_days_list_includes_only_business_days_with_window():
    start = build_business_instant(2026, 8, 24, 0, 0, BOGOTA)   # Lunes
    end = build_business_instant(2026, 8, 30, 23, 59, BOGOTA)   # Domingo
    days = get_candidate_days_list(start, end)
    assert [d["day"] for d in days] == [24, 26, 28]  # Lunes, Miercoles, Viernes


def test_get_candidate_days_list_excludes_holiday():
    # 2026-08-17 es lunes y tambien festivo en COLOMBIA_HOLIDAYS
    start = build_business_instant(2026, 8, 17, 0, 0, BOGOTA)
    end = build_business_instant(2026, 8, 17, 23, 59, BOGOTA)
    assert get_candidate_days_list(start, end) == []


def test_get_candidate_days_list_includes_first_saturday_of_month():
    start = build_business_instant(2026, 8, 1, 0, 0, BOGOTA)  # Sabado, dia 1
    end = build_business_instant(2026, 8, 1, 23, 59, BOGOTA)
    days = get_candidate_days_list(start, end)
    assert days == [{"year": 2026, "month": 8, "day": 1, "window": (8, 0, 12, 0)}]


# ---------------------------------------------------------------------------
# compute_available_slots
# ---------------------------------------------------------------------------

def _compute(**overrides):
    now = overrides.pop("now", build_business_instant(2026, 8, 20, 6, 0, BOGOTA))  # Jueves
    kwargs = dict(now=now, date_range_days=4, duration_minutes=30, user_tz=BOGOTA, busy_events=[])
    kwargs.update(overrides)
    return compute_available_slots(**kwargs)


def test_compute_available_slots_single_monday_window_no_busy_events():
    slots = _compute(interval_minutes=35)
    assert len(slots) == 8
    assert slots[0].start_co == "2026-08-24T07:00:00-05:00"
    assert slots[0].end_co == "2026-08-24T07:30:00-05:00"
    assert slots[-1].start_co == "2026-08-24T11:05:00-05:00"


def test_compute_available_slots_interval_zero_is_back_to_back():
    slots = _compute()
    assert len(slots) == 10
    assert [s.start_co[11:16] for s in slots[:3]] == ["07:00", "07:30", "08:00"]


def test_compute_available_slots_post_buffer_keeps_time_after_an_existing_appointment():
    busy = [(build_business_instant(2026, 8, 24, 8, 0, BOGOTA), build_business_instant(2026, 8, 24, 8, 30, BOGOTA))]
    plain = [s.start_co[11:16] for s in _compute(busy_events=busy)]
    buffered = [s.start_co[11:16] for s in _compute(busy_events=busy, post_buffer_minutes=10)]
    assert "08:30" in plain
    assert "08:30" not in buffered and "09:00" in buffered


def test_compute_available_slots_pre_buffer_keeps_time_before_an_existing_appointment():
    busy = [(build_business_instant(2026, 8, 24, 9, 0, BOGOTA), build_business_instant(2026, 8, 24, 9, 30, BOGOTA))]
    plain = [s.start_co[11:16] for s in _compute(busy_events=busy)]
    buffered = [s.start_co[11:16] for s in _compute(busy_events=busy, pre_buffer_minutes=10)]
    assert "08:30" in plain
    assert "08:30" not in buffered and "08:00" in buffered


def test_compute_available_slots_excludes_slot_overlapping_a_busy_event():
    busy = [(build_business_instant(2026, 8, 24, 8, 6, BOGOTA), build_business_instant(2026, 8, 24, 8, 8, BOGOTA))]
    starts = [s.start_co for s in _compute(busy_events=busy)]
    assert "2026-08-24T08:00:00-05:00" not in starts
    assert len(starts) == 9


def test_compute_available_slots_min_notice_replaces_the_next_business_day_rule():
    now = build_business_instant(2026, 8, 23, 20, 0, BOGOTA)  # domingo noche
    default = _compute(now=now, date_range_days=3)
    with_notice = _compute(now=now, date_range_days=3, min_notice_minutes=11 * 60)  # lunes 07:00 ya cumple
    assert default == [] or default[0].start_co[:10] != "2026-08-24"
    assert with_notice[0].start_co == "2026-08-24T07:00:00-05:00"
    stricter = _compute(now=now, date_range_days=3, min_notice_minutes=13 * 60)  # lunes 07:00 ya no
    assert all(s.start_co[:10] != "2026-08-24" or s.start_co[11:16] >= "09:00" for s in stricter)


def test_compute_available_slots_start_local_reflects_user_timezone():
    slots = _compute(user_tz="America/New_York")
    assert slots[0].start_local == "2026-08-24T08:00:00-04:00"


def test_compute_available_slots_returns_empty_when_no_candidate_days_in_range():
    assert _compute(date_range_days=0) == []
