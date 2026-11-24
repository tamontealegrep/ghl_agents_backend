from desk.services import slots_ivf, slots_sur
from desk.services.slot_engine import (
    compute_available_slots,
    compute_end_date,
    compute_start_date,
    is_holiday,
)

from agent_backend.timezones import build_business_instant

BOGOTA = "America/Bogota"


# ---------------------------------------------------------------------------
# compute_start_date — regla de anticipacion (code_01)
# ---------------------------------------------------------------------------


def test_start_date_weekday_adds_two_days():
    # Miercoles 2026-08-26 -> Viernes 2026-08-28
    """A weekday start date is two days ahead."""
    now = build_business_instant(2026, 8, 26, 10, 0, BOGOTA)
    assert compute_start_date(now).isoformat() == "2026-08-28T07:00:00-05:00"


def test_start_date_friday_before_5pm():
    """A Friday before 5 pm starts on Monday."""
    now = build_business_instant(2026, 8, 28, 10, 0, BOGOTA)  # Viernes, antes de 17h
    assert compute_start_date(now).isoformat() == "2026-08-31T07:00:00-05:00"


def test_start_date_friday_after_5pm():
    """A Friday after 5 pm starts on Tuesday."""
    now = build_business_instant(2026, 8, 28, 18, 0, BOGOTA)  # Viernes, 18h
    assert compute_start_date(now).isoformat() == "2026-09-01T07:00:00-05:00"


def test_start_date_saturday():
    """A Saturday starts on Tuesday."""
    now = build_business_instant(2026, 8, 29, 10, 0, BOGOTA)
    assert compute_start_date(now).isoformat() == "2026-09-01T07:00:00-05:00"


def test_start_date_sunday():
    """A Sunday starts on Tuesday."""
    now = build_business_instant(2026, 8, 30, 10, 0, BOGOTA)
    assert compute_start_date(now).isoformat() == "2026-09-01T07:00:00-05:00"


# ---------------------------------------------------------------------------
# compute_end_date — date_range_days dias despues, retrocede a viernes si cae fin de semana
# ---------------------------------------------------------------------------


def test_end_date_ivf_5pm():
    """The IVF end date always closes at 5 pm."""
    start = build_business_instant(2026, 9, 1, 7, 0, BOGOTA)  # +14 dias = 2026-09-15 (martes)
    end = compute_end_date(start, 14, slots_ivf.closing_hour)
    assert end.isoformat() == "2026-09-15T17:00:00-05:00"


def test_end_date_sur_4pm():
    """The SUR end date closes at 4 pm on a Tuesday."""
    start = build_business_instant(2026, 9, 1, 7, 0, BOGOTA)  # +14 dias = 2026-09-15 (martes)
    end = compute_end_date(start, 14, slots_sur.closing_hour)
    assert end.isoformat() == "2026-09-15T16:00:00-05:00"


def test_end_date_saturday_to_friday():
    # 2026-08-17 (lunes) + 14 dias = 2026-08-31 (lunes)... usamos una fecha
    # cuyo +14 caiga sabado: 2026-08-15 (sabado) es +14 de 2026-08-01 (sabado).
    """An end date on Saturday moves back to Friday."""
    start = build_business_instant(2026, 8, 1, 7, 0, BOGOTA)  # +14 = 2026-08-15, sabado
    end = compute_end_date(start, 14, slots_ivf.closing_hour)
    assert end.isoformat() == "2026-08-14T17:00:00-05:00"  # retrocede a viernes


def test_end_date_sunday_to_friday():
    # 2026-08-02 (domingo) es +14 de 2026-07-19 (domingo)
    """An end date on Sunday moves back to Friday, and SUR closes earlier."""
    start = build_business_instant(2026, 7, 19, 7, 0, BOGOTA)
    end = compute_end_date(start, 14, slots_sur.closing_hour)
    assert end.isoformat() == "2026-07-31T16:00:00-05:00"  # retrocede a viernes, no es lunes -> 16h


def test_end_date_uses_date_range():
    # Sabado 2026-08-29 + 7 dias = 2026-09-05 (sabado) -> retrocede a viernes 2026-09-04
    """The end date respects the configured date range."""
    start = build_business_instant(2026, 8, 29, 7, 0, BOGOTA)
    end = compute_end_date(start, 7, slots_ivf.closing_hour)
    assert end.isoformat() == "2026-09-04T17:00:00-05:00"


# ---------------------------------------------------------------------------
# is_holiday
# ---------------------------------------------------------------------------


def test_is_holiday_known_date():
    """A known holiday is detected."""
    assert is_holiday(2026, 1, 1) is True


def test_is_holiday_regular_date():
    """A regular date is not a holiday."""
    assert is_holiday(2026, 8, 26) is False


# ---------------------------------------------------------------------------
# compute_available_slots — un solo dia (viernes), politica IVF, sin ocupados
# ---------------------------------------------------------------------------


def test_slots_friday_excludes_lunch():
    """A single IVF Friday has 17 slots and none during lunch."""
    now = build_business_instant(2026, 8, 20, 6, 0, BOGOTA)  # jueves, lejos en el pasado
    start = build_business_instant(2026, 8, 28, 0, 0, BOGOTA)  # viernes
    end = build_business_instant(2026, 8, 28, 23, 59, BOGOTA)

    slots = compute_available_slots(
        start_date=start,
        end_date=end,
        now_utc=now,
        duration_minutes=30,
        interval_minutes=30,
        min_advance_minutes=60,
        user_tz=BOGOTA,
        busy_events=[],
        day_window_fn=slots_ivf.day_window,
        lunch_break_fn=slots_ivf.lunch_break,
    )

    assert len(slots) == 17
    assert slots[0].start_co == "2026-08-28T07:30:00-05:00"
    assert slots[-1].start_co == "2026-08-28T16:30:00-05:00"
    starts = [s.start_co for s in slots]
    assert "2026-08-28T12:00:00-05:00" not in starts
    assert "2026-08-28T12:30:00-05:00" not in starts
    assert "2026-08-28T13:00:00-05:00" in starts  # justo despues del almuerzo, si permitido
    assert "2026-08-28T13:30:00-05:00" in starts


def test_slots_exclude_holiday():
    """Holidays have no slots."""
    now = build_business_instant(2026, 8, 10, 6, 0, BOGOTA)
    # 2026-08-17 es lunes y tambien festivo colombiano
    start = build_business_instant(2026, 8, 17, 0, 0, BOGOTA)
    end = build_business_instant(2026, 8, 17, 23, 59, BOGOTA)

    slots = compute_available_slots(
        start_date=start,
        end_date=end,
        now_utc=now,
        duration_minutes=30,
        interval_minutes=30,
        min_advance_minutes=60,
        user_tz=BOGOTA,
        busy_events=[],
        day_window_fn=slots_ivf.day_window,
        lunch_break_fn=slots_ivf.lunch_break,
    )
    assert slots == []


def test_slots_exclude_busy_event():
    """Slots overlapping a busy event are excluded."""
    now = build_business_instant(2026, 8, 20, 6, 0, BOGOTA)
    start = build_business_instant(2026, 8, 28, 0, 0, BOGOTA)
    end = build_business_instant(2026, 8, 28, 23, 59, BOGOTA)
    busy_start = build_business_instant(2026, 8, 28, 9, 0, BOGOTA)
    busy_end = build_business_instant(2026, 8, 28, 9, 30, BOGOTA)

    slots = compute_available_slots(
        start_date=start,
        end_date=end,
        now_utc=now,
        duration_minutes=30,
        interval_minutes=30,
        min_advance_minutes=60,
        user_tz=BOGOTA,
        busy_events=[(busy_start, busy_end)],
        day_window_fn=slots_ivf.day_window,
        lunch_break_fn=slots_ivf.lunch_break,
    )
    starts = [s.start_co for s in slots]
    assert "2026-08-28T09:00:00-05:00" not in starts
    assert len(slots) == 16


def test_slots_respect_min_notice():
    # now muy cerca del inicio de la ventana: el slot de las 09:00 queda
    # dentro de los 60 minutos de anticipacion minima y debe excluirse.
    """Slots respect the minimum advance notice."""
    start = build_business_instant(2026, 8, 28, 0, 0, BOGOTA)
    end = build_business_instant(2026, 8, 28, 23, 59, BOGOTA)
    now = build_business_instant(2026, 8, 28, 8, 30, BOGOTA)  # 30 min antes de las 09:00

    slots = compute_available_slots(
        start_date=start,
        end_date=end,
        now_utc=now,
        duration_minutes=30,
        interval_minutes=30,
        min_advance_minutes=60,
        user_tz=BOGOTA,
        busy_events=[],
        day_window_fn=slots_ivf.day_window,
        lunch_break_fn=slots_ivf.lunch_break,
    )
    starts = [s.start_co for s in slots]
    assert "2026-08-28T09:00:00-05:00" not in starts
    assert "2026-08-28T09:30:00-05:00" in starts  # ya cumple los 60 min de anticipacion


def test_slots_local_start_uses_user_timezone():
    """Each slot's local start reflects the user's timezone."""
    now = build_business_instant(2026, 8, 20, 6, 0, BOGOTA)
    start = build_business_instant(2026, 8, 28, 0, 0, BOGOTA)
    end = build_business_instant(2026, 8, 28, 23, 59, BOGOTA)

    slots = compute_available_slots(
        start_date=start,
        end_date=end,
        now_utc=now,
        duration_minutes=30,
        interval_minutes=30,
        min_advance_minutes=60,
        user_tz="America/New_York",
        busy_events=[],
        day_window_fn=slots_ivf.day_window,
        lunch_break_fn=slots_ivf.lunch_break,
    )
    # 07:30 Bogota (-05:00) == 08:30 New York (-04:00, horario de verano en agosto)
    assert slots[0].start_local == "2026-08-28T08:30:00-04:00"
