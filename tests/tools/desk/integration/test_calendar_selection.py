"""A calendar declared in the environment is selectable by ``calendar_type`` in the tools."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from desk.api.v1.endpoints import book_appointment_ghl as book_endpoint
from desk.api.v1.endpoints import book_appointment_google as google_book_endpoint
from desk.api.v1.endpoints import calendars as calendars_endpoint
from desk.api.v1.endpoints import get_available_slots_ghl as slots_endpoint
from desk.core.config import ToolConfig
from fastapi.testclient import TestClient

from tests.tools.apps import desk_app as app

client = TestClient(app)


class _NoGmail:
    google_client_id = google_client_secret = google_refresh_token = sender_email = ""


class _Settings:
    gmail = _NoGmail()
    ghl_token = "token"
    ghl_location_id = "loc"
    calendars = {
        "IVF": ToolConfig("", "", "", "", "ivf-id", duration_minutes=30),
        "CONSULTA": ToolConfig("", "", "", "", "consulta-id", duration_minutes=20),
        "SIN_ID": ToolConfig("", "", "", "", "", duration_minutes=30),
    }


def _use_settings(monkeypatch, *modules):
    for module in modules:
        monkeypatch.setattr(module, "get_settings", lambda: _Settings())


def test_calendars_endpoint_lists_keys_without_leaking_ids(monkeypatch):
    _use_settings(monkeypatch, calendars_endpoint)

    body = client.get("/api/v1/calendars").json()

    assert [c["key"] for c in body["calendars"]] == ["IVF", "CONSULTA", "SIN_ID"]
    assert body["calendars"][1] == {"key": "CONSULTA", "ghl": True, "google": False}
    assert "consulta-id" not in str(body)


def test_slots_for_a_new_calendar_query_that_calendars_ghl_id(monkeypatch):
    seen = {}

    day = datetime.now(ZoneInfo("America/Bogota")).date() + timedelta(days=10)
    while day.isoweekday() != 4:  # a Thursday, inside the default window
        day += timedelta(days=1)

    async def _fake_free_slots(**kwargs):
        seen.update(kwargs)
        return [f"{day.isoformat()}T14:00:00Z"]  # 09:00 Bogota

    _use_settings(monkeypatch, slots_endpoint)
    monkeypatch.setattr(slots_endpoint, "ghl_get_available_slots", _fake_free_slots)
    monkeypatch.setattr(slots_endpoint, "is_holiday", lambda y, m, d: False)

    body = client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "consulta"}).json()

    assert seen["calendar_id"] == "consulta-id"
    assert body["success"] is True and len(body["available_slots"]) == 1
    # duration comes from that calendar's own configuration (20 min), not IVF's
    assert body["available_slots"][0]["start_co"][11:16] == "09:00"
    assert body["available_slots"][0]["end_co"][11:16] == "09:20"


def test_unknown_calendar_is_rejected_with_the_valid_keys(monkeypatch):
    _use_settings(monkeypatch, slots_endpoint)

    body = client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "NOPE"}).json()

    assert body["success"] is False
    assert "IVF, CONSULTA, SIN_ID" in body["errors"]


def test_calendar_without_ghl_id_names_the_variable_to_define(monkeypatch):
    _use_settings(monkeypatch, slots_endpoint)

    body = client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "SIN_ID"}).json()

    assert body["success"] is False
    assert "FA_GHL_CALENDAR_ID_SIN_ID" in body["errors"]


def test_booking_in_an_unknown_calendar_does_not_fall_back_to_ivf(monkeypatch):
    _use_settings(monkeypatch, book_endpoint)

    body = client.post(
        "/api/v1/book-appointment-ghl",
        json={
            "calendar_type": "NOPE",
            "start_date": "2030-01-07T15:00:00Z",
            "contact_name": "Ana",
            "contact_email": "ana.perez@gmail.com",
            "contact_phone": "+570000000",
            "language": "ES",
            "duration": "20",
            "iana_timezone": "America/Bogota",
        },
    ).json()

    assert body["success"] is False
    assert "Unknown calendar_type" in body["errors"]


class _GoogleCreds:
    google_client_id = google_client_secret = google_refresh_token = "x"
    calendar_id = "consulta@example.com"
    ghl_calendar_id = ""
    duration_minutes = 20
    interval_minutes = 0
    date_range_days = 14


class _GoogleSettings:
    calendars = {"CONSULTA": _GoogleCreds()}
    gmail = _NoGmail()


def test_new_calendar_without_email_template_books_without_sending_email(monkeypatch):
    async def _token(*args, **kwargs):
        return "token"

    async def _no_busy(*args, **kwargs):
        return []

    async def _create(*args, **kwargs):
        return {"id": "evt1", "htmlLink": "https://example.com/e", "hangoutLink": "https://meet.example.com/x"}

    monkeypatch.setattr(google_book_endpoint, "get_settings", lambda: _GoogleSettings())
    monkeypatch.setattr(google_book_endpoint, "get_access_token", _token)
    monkeypatch.setattr(google_book_endpoint, "get_free_busy", _no_busy)
    monkeypatch.setattr(google_book_endpoint, "create_event", _create)

    body = client.post(
        "/api/v1/book-appointment-google",
        json={
            "calendar_type": "consulta",
            "start_date": "2027-03-03T09:00:00-05:00",  # a Wednesday; no 2027 holidays configured
            "duration": "20",
            "contact_name": "Ana Perez",
            "contact_email": "ana.perez@gmail.com",
            "contact_phone": "+570000000",
            "language": "ES",
            "iana_timezone": "America/Bogota",
        },
    ).json()

    # Gmail credentials are empty: any attempt to send the email would put an error here.
    assert body.get("errors") is None, body
    assert body["success"] is True and body["event_id"] == "evt1"
    assert body["errors"] is None


def _book_with_notification(monkeypatch, notification_email, send):
    from desk.services import notifications

    class _Gmail:
        google_client_id = google_client_secret = google_refresh_token = "x"
        sender_email = "sender@example.org"

    class _Settings2(_GoogleSettings):
        gmail = _Gmail()

    _Settings2.notification_email = notification_email

    async def _token(*args, **kwargs):
        return "token"

    async def _no_busy(*args, **kwargs):
        return []

    async def _create(*args, **kwargs):
        return {"id": "evt1", "htmlLink": "https://example.com/e", "hangoutLink": "https://meet.example.com/x"}

    monkeypatch.setattr(google_book_endpoint, "get_settings", lambda: _Settings2())
    monkeypatch.setattr(google_book_endpoint, "get_access_token", _token)
    monkeypatch.setattr(google_book_endpoint, "get_free_busy", _no_busy)
    monkeypatch.setattr(google_book_endpoint, "create_event", _create)
    monkeypatch.setattr(notifications, "get_access_token", _token)
    monkeypatch.setattr(notifications, "send_email", send)

    return client.post(
        "/api/v1/book-appointment-google",
        json={
            "calendar_type": "consulta",
            "start_date": "2027-03-03T09:00:00-05:00",
            "duration": "20",
            "contact_name": "Ana Perez",
            "contact_email": "ana.perez@gmail.com",
            "contact_phone": "+570000000",
            "language": "ES",
            "iana_timezone": "America/Bogota",
        },
    ).json()


def test_booking_notifies_the_internal_address_when_configured(monkeypatch):
    sent = []

    async def _send(token, sender, to, subject, html):
        sent.append(to)
        return {}

    body = _book_with_notification(monkeypatch, "team@example.org", _send)

    assert body["success"] is True and body["errors"] is None
    assert sent == ["team@example.org"]


def test_booking_stays_successful_when_the_notification_fails(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("gmail down")

    body = _book_with_notification(monkeypatch, "team@example.org", _boom)

    assert body["success"] is True and body["event_id"] == "evt1"
    assert "FA_NOTIFICATION_EMAIL" in body["errors"] and "gmail down" in body["errors"]


def test_booking_sends_no_notification_when_not_configured(monkeypatch):
    sent = []

    async def _send(*args, **kwargs):
        sent.append(args)
        return {}

    body = _book_with_notification(monkeypatch, "", _send)

    assert body["success"] is True and sent == []
