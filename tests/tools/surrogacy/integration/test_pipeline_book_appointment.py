"""Prueba el endpoint /book-appointment de punta a punta con Google Calendar y Gmail mockeados."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from surrogacy.api.v1.endpoints import book_appointment_google as endpoint
from surrogacy.services import notifications

from tests.tools.apps import surrogacy_app as app

client = TestClient(app)


def _next_business_datetime_iso(hour: int = 9, minute: int = 0) -> str:
    now = datetime.now(ZoneInfo("America/Bogota"))
    candidate = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    while candidate.weekday() == 6 or candidate <= now:  # domingo (Python weekday 6) cerrado
        candidate += timedelta(days=1)
    return candidate.isoformat()


def _valid_payload() -> dict:
    return {
        "start_date": _next_business_datetime_iso(),
        "duration": "10",
        "contact_name": "ana   GOMEZ",
        "contact_email": "ana@example.com",
        "contact_phone": "+573007654321",
        "iana_timezone": "America/Bogota",
        "calendar_type": "FT",
    }


class _FakeSettings:
    google_client_id = "fake-client-id"
    google_client_secret = "fake-client-secret"
    google_refresh_token = "fake-refresh-token"
    calendar_id = "c_fake@group.calendar.google.com"
    notification_email = "contact-center@novafem.com.co"

    class gmail:
        google_client_id = "fake-gmail-id"
        google_client_secret = "fake-gmail-secret"
        google_refresh_token = "fake-gmail-refresh"
        sender_email = "no-reply@novafem.com.co"


_FakeSettings.calendars = {"FT": _FakeSettings}


class _EmptyCalendarSettings(_FakeSettings):
    google_client_id = ""
    google_client_secret = ""
    google_refresh_token = ""


_EmptyCalendarSettings.calendars = {"FT": _EmptyCalendarSettings}


class _EmptyNotificationSettings(_FakeSettings):
    notification_email = ""


_EmptyNotificationSettings.calendars = {"FT": _EmptyNotificationSettings}


class _EmptyGmailSettings(_FakeSettings):
    class gmail:
        google_client_id = ""
        google_client_secret = "fake-gmail-secret"
        google_refresh_token = "fake-gmail-refresh"
        sender_email = "no-reply@novafem.com.co"


_EmptyGmailSettings.calendars = {"FT": _EmptyGmailSettings}


async def _fake_get_access_token(*args, **kwargs):
    return "fake-access-token"


async def _fake_create_event(*args, **kwargs):
    return {
        "id": "evt789",
        "htmlLink": "https://calendar.google.com/event?eid=ghi",
        "hangoutLink": "https://meet.google.com/rst-uvwx",
    }


async def _fake_create_event_no_id(*args, **kwargs):
    return {}


async def _fake_send_email(*args, **kwargs):
    return {"id": "msg789"}


@pytest.fixture
def mocked_success(monkeypatch):
    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "create_event", _fake_create_event)
    monkeypatch.setattr(notifications, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(notifications, "send_email", _fake_send_email)


def test_booking_succeeds(mocked_success):
    """A booking succeeds and returns the event id."""
    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["event_id"] == "evt789"
    assert body["errors"] is None


def test_booking_rejects_past_date(mocked_success):
    """A date in the past is rejected."""
    payload = _valid_payload()
    payload["start_date"] = "2020-01-01T09:00:00-05:00"
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "past_date"


def test_booking_rejects_invalid_date(mocked_success):
    """An unparsable start date is rejected."""
    payload = _valid_payload()
    payload["start_date"] = "no-es-una-fecha"
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "invalid_start_date"


def test_booking_rejects_outside_hours(mocked_success):
    """A time outside business hours is rejected."""
    payload = _valid_payload()
    payload["start_date"] = _next_business_datetime_iso(hour=20)
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "invalid_hour"


def test_booking_rejects_sunday(mocked_success):
    """A Sunday booking is rejected."""
    now = datetime.now(ZoneInfo("America/Bogota"))
    days_until_sunday = (6 - now.weekday()) % 7 or 7
    next_sunday = (now + timedelta(days=days_until_sunday)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    payload = _valid_payload()
    payload["start_date"] = next_sunday.isoformat()
    response = client.post("/api/v1/book-appointment-google", json=payload)
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "invalid_hour"


def test_booking_reports_creation_failed(monkeypatch):
    """A calendar creation error is reported."""
    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "create_event", _fake_create_event_no_id)

    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    body = response.json()
    assert body["success"] is False
    assert body["reason"] == "creation_failed"


def test_booking_missing_credentials(monkeypatch):
    """Missing calendar credentials give an error in the body, not an HTTP failure."""
    monkeypatch.setattr(endpoint, "get_settings", lambda: _EmptyCalendarSettings())

    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    body = response.json()
    assert body["success"] is False
    assert "GOOGLE_CLIENT_ID" in body["errors"]


def _capture_emails(monkeypatch):
    sent = []

    async def _send(token, sender, to, subject, html):
        sent.append({"to": to, "subject": subject, "html": html})
        return {}

    monkeypatch.setattr(notifications, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(notifications, "send_email", _send)
    return sent


def _book(monkeypatch, settings_cls):
    monkeypatch.setattr(endpoint, "get_settings", lambda: settings_cls())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "create_event", _fake_create_event)
    return client.post("/api/v1/book-appointment-google", json=_valid_payload()).json()


def test_booking_no_email_sends_nothing(monkeypatch):
    """Without a notification email nothing is sent."""
    sent = _capture_emails(monkeypatch)

    body = _book(monkeypatch, _EmptyNotificationSettings)

    assert body["success"] is True and body["errors"] is None
    assert sent == []


def test_booking_notifies_team_not_patient(monkeypatch):
    """The team is notified, never the patient."""
    sent = _capture_emails(monkeypatch)

    body = _book(monkeypatch, _FakeSettings)

    assert body["success"] is True and body["errors"] is None
    assert [m["to"] for m in sent] == ["contact-center@novafem.com.co"]
    assert "ana@example.com" not in sent[0]["to"]
    assert "+573007654321" in sent[0]["html"]


def test_booking_one_message_all_addresses(monkeypatch):
    """Every configured address gets the same single message."""
    sent = _capture_emails(monkeypatch)

    class _Many(_FakeSettings):
        notification_email = "a@example.org, b@example.org"

    _Many.calendars = {"FT": _Many}
    _book(monkeypatch, _Many)

    assert len(sent) == 1 and sent[0]["to"] == "a@example.org, b@example.org"


def test_booking_survives_email_failure(monkeypatch):
    """The booking succeeds even if the notification email fails."""
    monkeypatch.setattr(endpoint, "get_settings", lambda: _EmptyGmailSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "create_event", _fake_create_event)

    response = client.post("/api/v1/book-appointment-google", json=_valid_payload())
    body = response.json()
    assert body["success"] is True
    assert body["event_id"] == "evt789"
    assert "BN_NOTIFICATION_EMAIL" in body["errors"]
