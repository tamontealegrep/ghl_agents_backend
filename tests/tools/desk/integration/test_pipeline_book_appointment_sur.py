"""
Prueba el endpoint /book-appointment-sur de punta a punta con Google Calendar y Gmail mockeados.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from desk.api.v1.endpoints import book_appointment_google as endpoint
from fastapi.testclient import TestClient

from tests.tools.apps import desk_app as app

client = TestClient(app)


def _next_business_datetime_iso(hour: int = 9, minute: int = 0) -> str:
    now = datetime.now(ZoneInfo("America/Bogota"))
    candidate = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    while candidate.weekday() >= 5 or candidate <= now:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _valid_payload() -> dict:
    return {
        "calendar_type": "SUR",
        "start_date": _next_business_datetime_iso(),
        "duration": "20",
        "contact_name": "ana   GOMEZ",
        "contact_email": "ana@correo-cliente.com",
        "contact_phone": "+573007654321",
        "language": "EN",
        "iana_timezone": "America/New_York",
    }


class _FakeCreds:
    google_client_id = "fake-client-id"
    google_client_secret = "fake-client-secret"
    google_refresh_token = "fake-refresh-token"
    calendar_id = "marango@familyaims.com"
    duration_minutes = 20
    interval_minutes = 10
    date_range_days = 7


class _EmptyCreds(_FakeCreds):
    google_client_id = ""
    google_client_secret = ""
    google_refresh_token = ""


class _FakeGmail:
    google_client_id = "fake-gmail-id"
    google_client_secret = "fake-gmail-secret"
    google_refresh_token = "fake-gmail-refresh"
    sender_email = "no-reply@familyaims.com"


class _EmptyGmail(_FakeGmail):
    google_client_id = ""


class _FakeSettings:
    sur = _FakeCreds()
    gmail = _FakeGmail()
    calendars = {"SUR": sur}


class _EmptyToolSettings:
    sur = _EmptyCreds()
    gmail = _FakeGmail()
    calendars = {"SUR": sur}


class _EmptyGmailSettings:
    sur = _FakeCreds()
    gmail = _EmptyGmail()
    calendars = {"SUR": sur}


async def _fake_get_access_token(*args, **kwargs):
    return "fake-access-token"


async def _fake_get_free_busy_empty(*args, **kwargs):
    return []


async def _fake_get_free_busy_busy(*args, **kwargs):
    now = datetime.now(ZoneInfo("UTC"))
    return [(now, now + timedelta(minutes=30))]


async def _fake_create_event(*args, **kwargs):
    return {
        "id": "evt456",
        "htmlLink": "https://calendar.google.com/event?eid=def",
        "hangoutLink": "https://meet.google.com/uvw-lmno",
    }


async def _fake_create_event_no_id(*args, **kwargs):
    return {}


async def _fake_send_email(*args, **kwargs):
    return {"id": "msg456"}


@pytest.fixture
def mocked_success(monkeypatch):
    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "get_free_busy", _fake_get_free_busy_empty)
    monkeypatch.setattr(endpoint, "create_event", _fake_create_event)
    monkeypatch.setattr(endpoint, "send_email", _fake_send_email)


def test_sur_booking_succeeds(mocked_success):
    """A SUR booking succeeds and returns the event id."""
    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["event_id"] == "evt456"
    assert body["errors"] is None


def test_sur_rejects_invalid_email(mocked_success):
    """An invalid email is rejected."""
    payload = _valid_payload()
    payload["contact_email"] = "no-es-un-correo"
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "invalid_email"


def test_sur_rejects_past_date(mocked_success):
    """A date in the past is rejected."""
    payload = _valid_payload()
    payload["start_date"] = "2020-01-01T09:00:00-05:00"
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "past_date"


def test_sur_rejects_outside_hours(mocked_success):
    """A time outside business hours is rejected."""
    payload = _valid_payload()
    payload["start_date"] = _next_business_datetime_iso(hour=20)
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "invalid_hour"


def test_sur_monday_after_2pm_rejected(mocked_success):
    """On Mondays SUR does not book after 2 pm."""
    now = datetime.now(ZoneInfo("America/Bogota"))
    days_until_monday = (7 - now.weekday()) % 7 or 7
    next_monday = (now + timedelta(days=days_until_monday)).replace(
        hour=15, minute=0, second=0, microsecond=0
    )
    payload = _valid_payload()
    payload["start_date"] = next_monday.isoformat()
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "invalid_hour"


def test_sur_reports_slot_taken(monkeypatch):
    """A busy slot is reported as taken."""
    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "get_free_busy", _fake_get_free_busy_busy)

    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "slot_taken"


def test_sur_reports_creation_failed(monkeypatch):
    """A calendar creation error is reported."""
    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "get_free_busy", _fake_get_free_busy_empty)
    monkeypatch.setattr(endpoint, "create_event", _fake_create_event_no_id)

    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "creation_failed"


def test_sur_missing_credentials_is_graceful(monkeypatch):
    """Missing calendar credentials give an error in the body, not an HTTP failure."""
    monkeypatch.setattr(endpoint, "get_settings", lambda: _EmptyToolSettings())

    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    body = response.json()
    assert body["success"] is False
    assert "GOOGLE_CLIENT_ID_SUR" in body["errors"]


def test_sur_booking_survives_email_failure(monkeypatch):
    """The booking succeeds and reports the e-mail failure when the notification cannot be sent."""
    monkeypatch.setattr(endpoint, "get_settings", lambda: _EmptyGmailSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "get_free_busy", _fake_get_free_busy_empty)
    monkeypatch.setattr(endpoint, "create_event", _fake_create_event)

    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    body = response.json()
    assert body["success"] is True
    assert body["event_id"] == "evt456"
    assert "email notification failed" in body["errors"]
