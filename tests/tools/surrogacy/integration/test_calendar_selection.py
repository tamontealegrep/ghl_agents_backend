"""BabyNova's scheduling tools work on the calendar named by ``calendar_type``."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agent_backend.calendars import CalendarSettings
from fastapi.testclient import TestClient

from surrogacy.api.v1.endpoints import book_appointment_google as book_endpoint
from surrogacy.api.v1.endpoints import cancel_appointment_google as cancel_endpoint
from surrogacy.api.v1.endpoints import edit_appointment_google as edit_endpoint
from surrogacy.api.v1.endpoints import find_appointment_google as find_endpoint
from surrogacy.api.v1.endpoints import get_available_slots_google as slots_endpoint
from surrogacy.services import notifications
from tests.tools.apps import surrogacy_app as app

client = TestClient(app)


class _Gmail:
    google_client_id = google_client_secret = google_refresh_token = "x"
    sender_email = "sender@example.org"


class _Settings:
    notification_email = "team@example.org"
    gmail = _Gmail()
    calendars = {
        "FT": CalendarSettings("ft-id", "ft-sec", "ft-ref", "ft@cal", ""),
        "CONTROL": CalendarSettings("c-id", "c-sec", "c-ref", "control@cal", "", duration_minutes=20, date_range_days=7),
        "SIN_CREDENCIALES": CalendarSettings("", "", "", "", ""),
    }


def _use(monkeypatch, *modules):
    for module in modules:
        monkeypatch.setattr(module, "get_settings", lambda: _Settings())


async def _token(*args, **kwargs):
    return "token"


def test_slots_use_the_requested_calendars_credentials_hours_and_timings(monkeypatch):
    seen = {}

    async def _busy(access_token, calendar_id, start, end):
        seen["calendar_id"] = calendar_id
        return []

    async def _tok(client_id, client_secret, refresh_token):
        seen["client_id"] = client_id
        return "token"

    _use(monkeypatch, slots_endpoint)
    monkeypatch.setattr(slots_endpoint, "get_access_token", _tok)
    monkeypatch.setattr(slots_endpoint, "get_free_busy", _busy)

    body = client.post("/api/v1/get-available-slots-google", json={"calendar_type": "control"}).json()

    assert seen == {"client_id": "c-id", "calendar_id": "control@cal"}
    assert body["success"] is True and body["available_slots"]
    for slot in body["available_slots"]:
        start = datetime.fromisoformat(slot["start_co"])
        end = datetime.fromisoformat(slot["end_co"])
        assert end - start == timedelta(minutes=20)  # CONTROL's own duration
        assert start.isoweekday() <= 5  # default hours: Monday to Friday
        assert not (12 <= start.hour < 13)  # default lunch break


def test_every_scheduling_tool_fails_when_calendar_type_is_missing(monkeypatch):
    _use(monkeypatch, slots_endpoint, book_endpoint, cancel_endpoint, edit_endpoint, find_endpoint)
    payloads = {
        "get-available-slots-google": {},
        "book-appointment-google": {"start_date": "2030-01-07T15:00:00Z", "contact_name": "Ana", "contact_email": "a@b.co", "contact_phone": "1"},
        "cancel-appointment-google": {"event_id": "e"},
        "edit-appointment-google": {"event_id": "e"},
        "find-appointment-google": {"contact_name": "Ana"},
    }
    for tool, payload in payloads.items():
        for body_calendar in ({}, {"calendar_type": ""}, {"calendar_type": None}):
            body = client.post(f"/api/v1/{tool}", json={**payload, **body_calendar}).json()
            assert body["success"] is False, tool
            assert "calendar_type is required" in body["errors"], tool
            assert "FT, CONTROL, SIN_CREDENCIALES" in body["errors"], tool


def test_every_scheduling_tool_rejects_an_unknown_calendar_with_the_valid_keys(monkeypatch):
    _use(monkeypatch, slots_endpoint, book_endpoint, cancel_endpoint, edit_endpoint, find_endpoint)
    payloads = {
        "get-available-slots-google": {},
        "book-appointment-google": {"start_date": "2030-01-07T15:00:00Z", "contact_name": "Ana", "contact_email": "a@b.co", "contact_phone": "1"},
        "cancel-appointment-google": {"event_id": "e"},
        "edit-appointment-google": {"event_id": "e"},
        "find-appointment-google": {"contact_name": "Ana"},
    }
    for tool, payload in payloads.items():
        body = client.post(f"/api/v1/{tool}", json={**payload, "calendar_type": "NOPE"}).json()
        assert body["success"] is False, tool
        assert "FT, CONTROL, SIN_CREDENCIALES" in body["errors"], tool


def test_cancel_and_find_use_the_requested_calendar(monkeypatch):
    seen = []

    async def _delete(access_token, calendar_id, event_id):
        seen.append(("delete", calendar_id))
        return True

    async def _list(access_token, calendar_id, *args, **kwargs):
        seen.append(("list", calendar_id))
        return []

    _use(monkeypatch, cancel_endpoint, find_endpoint)
    monkeypatch.setattr(cancel_endpoint, "get_access_token", _token)
    monkeypatch.setattr(cancel_endpoint, "delete_event", _delete)
    monkeypatch.setattr(find_endpoint, "get_access_token", _token)
    monkeypatch.setattr(find_endpoint, "list_events", _list)

    client.post("/api/v1/cancel-appointment-google", json={"event_id": "e", "calendar_type": "CONTROL"})
    client.post("/api/v1/find-appointment-google", json={"contact_name": "Ana", "calendar_type": "CONTROL"})

    assert seen == [("delete", "control@cal"), ("list", "control@cal")]


def test_calendar_without_credentials_names_the_variables_to_define(monkeypatch):
    _use(monkeypatch, slots_endpoint)

    body = client.post("/api/v1/get-available-slots-google", json={"calendar_type": "sin_credenciales"}).json()

    assert body["success"] is False
    assert "BN_GOOGLE_CLIENT_ID_SIN_CREDENCIALES" in body["errors"]


def _monday_at(hour: int) -> str:
    day = datetime.now(ZoneInfo("America/Bogota")) + timedelta(days=3)
    while day.isoweekday() != 1:
        day += timedelta(days=1)
    return day.replace(hour=hour, minute=0, second=0, microsecond=0).isoformat()


def test_booking_in_a_new_calendar_uses_its_hours_title_and_notifies_the_team(monkeypatch):
    created = {}
    sent = []

    async def _create(**kwargs):
        created.update(kwargs)
        return {"id": "evt1", "htmlLink": "l", "hangoutLink": "m"}

    async def _send(token, sender, to, subject, html):
        sent.append((to, subject))
        return {}

    _use(monkeypatch, book_endpoint)
    monkeypatch.setattr(book_endpoint, "get_access_token", _token)
    monkeypatch.setattr(book_endpoint, "create_event", _create)
    monkeypatch.setattr(notifications, "get_access_token", _token)
    monkeypatch.setattr(notifications, "send_email", _send)

    payload = {
        "calendar_type": "control",
        "start_date": _monday_at(9),
        "duration": "20",
        "contact_name": "ana gomez",
        "contact_email": "ana@gmail.com",
        "contact_phone": "+573000000000",
    }
    body = client.post("/api/v1/book-appointment-google", json=payload).json()

    assert body["success"] is True and body["errors"] is None
    assert created["calendar_id"] == "control@cal"
    assert created["summary"].startswith("CONTROL - Ana Gomez")
    assert sent and sent[0][0] == "team@example.org" and sent[0][1].startswith("CONTROL - ")

    # The default hours end at 18:00: 19:00 is rejected for this calendar.
    late = client.post("/api/v1/book-appointment-google", json={**payload, "start_date": _monday_at(19)}).json()
    assert late["reason"] == "invalid_hour"
