"""The calendar parameters of the .env (interval, buffers, minimum notice, date range) on top of GHL's free slots."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from desk.api.v1.endpoints import book_appointment_ghl as book_endpoint
from desk.api.v1.endpoints import edit_appointment_ghl as edit_endpoint
from desk.api.v1.endpoints import get_available_slots_ghl as slots_endpoint
from fastapi.testclient import TestClient

from tests.tools.apps import desk_app as app

client = TestClient(app)
BOGOTA = ZoneInfo("America/Bogota")


def _tool(**overrides):
    values = dict(
        ghl_calendar_id="cal",
        duration_minutes=30,
        interval_minutes=0,
        pre_buffer_minutes=0,
        post_buffer_minutes=0,
        min_notice_minutes=None,
        date_range_days=14,
        google_client_id="",
        google_client_secret="",
        google_refresh_token="",
        calendar_id="",
    )
    values.update(overrides)
    return type("Tool", (), values)()


def _settings(**tool_overrides):
    tool = _tool(**tool_overrides)

    class _Gmail:
        google_client_id = google_client_secret = google_refresh_token = sender_email = ""

    class _Settings:
        ghl_token = "token"
        ghl_location_id = "loc"
        notification_email = ""
        gmail = _Gmail()
        calendars = {"IVF": tool}

    return _Settings()


def _day(iso_weekday: int = 4, min_days: int = 3):
    day = datetime.now(BOGOTA).date() + timedelta(days=min_days)
    while day.isoweekday() != iso_weekday:
        day += timedelta(days=1)
    return day


def _at(day, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=BOGOTA)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _event(start: datetime, end: datetime, event_id: str = "e1") -> dict:
    return {"id": event_id, "startTime": _iso(start), "endTime": _iso(end)}


def _slots(monkeypatch, tool_overrides, free, events=None, events_error=None):
    seen = {"free": {}, "events_calls": 0}

    async def _free(**kwargs):
        seen["free"] = kwargs
        return [_iso(m) for m in free]

    async def _events(**kwargs):
        seen["events_calls"] += 1
        if events_error:
            raise events_error
        return {"events": events or []}

    monkeypatch.setattr(slots_endpoint, "get_settings", lambda: _settings(**tool_overrides))
    monkeypatch.setattr(slots_endpoint, "ghl_get_available_slots", _free)
    monkeypatch.setattr(slots_endpoint, "ghl_list_events", _events)
    monkeypatch.setattr(slots_endpoint, "is_holiday", lambda y, m, d: False)
    body = client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "IVF"}).json()
    return body, seen


def _starts(body):
    return [s["start_co"][11:16] for s in body["available_slots"]]


def test_the_configured_duration_is_sent_to_ghl(monkeypatch):
    day = _day()
    _, seen = _slots(monkeypatch, {"duration_minutes": 20}, [_at(day, 9)])
    assert seen["free"]["duration_minutes"] == 20


def test_post_buffer_keeps_free_time_after_an_existing_appointment(monkeypatch):
    day = _day()
    free = [_at(day, 9, 0), _at(day, 9, 30), _at(day, 9, 40), _at(day, 10, 0)]
    events = [_event(_at(day, 9, 0), _at(day, 9, 30))]

    body, seen = _slots(monkeypatch, {"post_buffer_minutes": 10}, free[1:], events)

    # GHL says 09:30 is free, but the appointment ends at 09:30 and the calendar keeps 10 minutes after it.
    assert _starts(body) == ["09:40", "10:00"]
    assert seen["events_calls"] == 1


def test_pre_buffer_keeps_free_time_before_an_existing_appointment(monkeypatch):
    day = _day()
    free = [_at(day, 9, 20), _at(day, 9, 30)]
    events = [_event(_at(day, 10, 0), _at(day, 10, 30))]

    body, _ = _slots(monkeypatch, {"pre_buffer_minutes": 10}, free, events)

    assert _starts(body) == ["09:20"]


def test_without_buffers_the_events_are_not_even_requested(monkeypatch):
    day = _day()
    body, seen = _slots(
        monkeypatch, {}, [_at(day, 9), _at(day, 9, 30)], [_event(_at(day, 9), _at(day, 9, 30))]
    )
    assert _starts(body) == ["09:00", "09:30"]
    assert seen["events_calls"] == 0


def test_if_ghl_events_cannot_be_read_the_slots_are_offered_unfiltered(monkeypatch):
    day = _day()
    body, _ = _slots(
        monkeypatch,
        {"post_buffer_minutes": 10},
        [_at(day, 9), _at(day, 9, 30)],
        events_error=RuntimeError("boom"),
    )
    assert body["success"] is True and _starts(body) == ["09:00", "09:30"]


def test_interval_keeps_offered_starts_apart(monkeypatch):
    day = _day()
    free = [_at(day, 9, m) for m in (0, 30)] + [_at(day, 10, m) for m in (0, 30)] + [_at(day, 11)]
    body, _ = _slots(monkeypatch, {"interval_minutes": 60}, free)
    assert _starts(body) == ["09:00", "10:00", "11:00"]


def test_interval_zero_offers_every_slot(monkeypatch):
    day = _day()
    body, _ = _slots(monkeypatch, {"interval_minutes": 0}, [_at(day, 9), _at(day, 9, 30)])
    assert _starts(body) == ["09:00", "09:30"]


def test_min_notice_sets_the_earliest_slot_and_discards_earlier_ones(monkeypatch):
    soon = _day(min_days=3)
    later = _day(min_days=12)
    body, seen = _slots(monkeypatch, {"min_notice_minutes": 10 * 24 * 60}, [_at(soon, 9), _at(later, 9)])

    assert _starts(body) == ["09:00"]
    assert body["available_slots"][0]["start_co"][:10] == later.isoformat()
    asked = seen["free"]["start_dt"]
    assert abs((asked - datetime.now(UTC) - timedelta(days=10)).total_seconds()) < 60


def test_a_date_range_longer_than_ghls_limit_is_rejected_naming_the_variable(monkeypatch):
    body, seen = _slots(monkeypatch, {"date_range_days": 45}, [])
    assert body["success"] is False
    assert "FA_DATE_RANGE_DAYS_IVF" in body["errors"] and "31" in body["errors"]
    assert seen["free"] == {}


# --- booking ---------------------------------------------------------------------


def _book(monkeypatch, tool_overrides, start: datetime, events, free=None):
    async def _free(**kwargs):
        return [_iso(m) for m in (free if free is not None else [start])]

    async def _events(**kwargs):
        return {"events": events}

    monkeypatch.setattr(book_endpoint, "get_settings", lambda: _settings(**tool_overrides))
    monkeypatch.setattr(book_endpoint, "ghl_get_available_slots", _free)
    monkeypatch.setattr(book_endpoint, "ghl_list_events", _events)
    monkeypatch.setattr(book_endpoint.engine_slots, "is_holiday", lambda y, m, d: False)
    return client.post(
        "/api/v1/book-appointment-ghl",
        json={
            "calendar_type": "IVF",
            "start_date": start.isoformat(),
            "duration": "30",
            "contact_name": "Ana Perez",
            "contact_email": "ana.perez@gmail.com",
            "contact_phone": "+570000000",
            "contact_id": "c1",
            "language": "ES",
            "iana_timezone": "America/Bogota",
        },
    ).json()


def test_booking_is_refused_inside_the_post_buffer_of_another_appointment(monkeypatch):
    day = _day()
    start = _at(day, 9, 30)
    events = [_event(_at(day, 9, 0), _at(day, 9, 30))]

    body = _book(monkeypatch, {"post_buffer_minutes": 10}, start, events)

    assert body["success"] is False and body["reason"] == "slot_taken"


def test_booking_is_refused_when_it_leaves_no_pre_buffer_before_the_next_appointment(monkeypatch):
    day = _day()
    start = _at(day, 9, 30)  # 09:30-10:00, the next appointment starts at 10:00
    events = [_event(_at(day, 10, 0), _at(day, 10, 30))]

    assert _book(monkeypatch, {"pre_buffer_minutes": 10}, start, events)["reason"] == "slot_taken"


def test_booking_respects_the_minimum_notice_of_the_calendar(monkeypatch):
    start = _at(_day(min_days=3), 9)

    body = _book(monkeypatch, {"min_notice_minutes": 10 * 24 * 60}, start, [])

    assert body["success"] is False and "minimum advance notice" in body["errors"]


def test_booking_beyond_the_date_range_is_refused(monkeypatch):
    start = _at(_day(min_days=30), 9)

    body = _book(monkeypatch, {"date_range_days": 14}, start, [])

    assert body["success"] is False and "booking window" in body["errors"]


# --- editing ----------------------------------------------------------------------


def test_rescheduling_ignores_the_event_itself_but_not_the_buffers_of_others(monkeypatch):
    day = _day()
    new_start = _at(day, 9, 30)
    events = [
        _event(_at(day, 9, 0), _at(day, 9, 30), event_id="other"),
        _event(_at(day, 14, 0), _at(day, 14, 30), event_id="mine"),
    ]

    async def _events(**kwargs):
        return {"events": events}

    monkeypatch.setattr(edit_endpoint, "get_settings", lambda: _settings(post_buffer_minutes=10))
    monkeypatch.setattr(edit_endpoint, "ghl_list_events", _events)

    body = client.post(
        "/api/v1/edit-appointment-ghl",
        json={
            "calendar_type": "IVF",
            "event_id": "mine",
            "new_start_date": new_start.isoformat(),
            "new_duration": "30",
        },
    ).json()

    assert body["success"] is False and "already taken" in body["errors"]
