"""
Prueba que /get-available-slots-ghl aplica las restricciones de horario sobre los slots libres de GHL.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from desk.api.v1.endpoints import get_available_slots_ghl as endpoint
from fastapi.testclient import TestClient

from tests.tools.apps import desk_app as app

client = TestClient(app)


class _FakeTool:
    ghl_calendar_id = "cal"
    duration_minutes = 30
    interval_minutes = 0
    pre_buffer_minutes = 0
    post_buffer_minutes = 0
    min_notice_minutes = None
    date_range_days = 14


class _FakeSettings:
    ghl_token = "token"
    ivf = _FakeTool()
    calendars = {"IVF": ivf}


def _future_weekday(iso_weekday: int, min_days: int = 10):
    """A date at least ``min_days`` ahead that falls on the given ISO weekday (1 = Monday)."""
    day = datetime.now(ZoneInfo("America/Bogota")).date() + timedelta(days=min_days)
    while day.isoweekday() != iso_weekday:
        day += timedelta(days=1)
    return day


def _free_slot(hour: int, day, minute: int = 0) -> str:
    # Hora de Bogotá (UTC-5) expresada en UTC, como la devuelve GHL.
    return f"{day.isoformat()}T{hour + 5:02d}:{minute:02d}:00Z"


def test_ghl_slots_outside_the_window_the_lunch_break_and_holidays_are_dropped(monkeypatch):
    thursday = _future_weekday(4)
    holiday = _future_weekday(2)

    async def _fake_free_slots(**kwargs):
        return [
            _free_slot(6, thursday),
            _free_slot(7, thursday),  # the day opens at 07:30
            _free_slot(7, thursday, 30),
            _free_slot(11, thursday, 30),  # 11:30-12:00 ends exactly when lunch starts
            _free_slot(11, thursday, 40),  # 11:40-12:10 overlaps lunch
            _free_slot(12, thursday),
            _free_slot(12, thursday, 50),  # 12:50-13:30 overlaps the end of lunch
            _free_slot(13, thursday),
            _free_slot(17, thursday),
            _free_slot(9, holiday),  # festivo
        ]

    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(endpoint, "ghl_get_available_slots", _fake_free_slots)
    monkeypatch.setattr(endpoint, "is_holiday", lambda y, m, d: (y, m, d) == (holiday.year, holiday.month, holiday.day))

    response = client.post("/api/v1/get-available-slots-ghl", json={"iana_timezone": "America/Bogota", "calendar_type": "IVF"})

    assert response.status_code == 200
    starts = [slot["start_co"] for slot in response.json()["available_slots"]]
    assert [s[11:16] for s in starts] == ["07:30", "11:30", "13:00"]
