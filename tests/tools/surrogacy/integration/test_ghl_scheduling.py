"""BabyNova mounts the shared GHL scheduling tools with its own calendars, hours and team notification."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from surrogacy.api.v1.endpoints import ghl_scheduling as endpoint
from surrogacy.services import calendars as calendars_service
from surrogacy.services import notifications

from agent_backend import ghl_calendar
from agent_backend.calendars import CalendarSettings
from tests.tools.apps import surrogacy_app as app

client = TestClient(app)
BOGOTA = ZoneInfo("America/Bogota")


class _Gmail:
    google_client_id = google_client_secret = google_refresh_token = "x"
    sender_email = "sender@example.org"


class _Settings:
    ghl_token = "token"
    ghl_location_id = "loc"
    notification_email = "team@example.org"
    gmail = _Gmail()
    calendars = {
        "FT": CalendarSettings("", "", "", "primary", "ft-cal", duration_minutes=30, post_buffer_minutes=15),
        "CONTROL": CalendarSettings("", "", "", "", "control-cal", duration_minutes=20),
    }


def _day(iso_weekday: int, min_days: int = 10):
    d = datetime.now(BOGOTA).date() + timedelta(days=min_days)
    while d.isoweekday() != iso_weekday:
        d += timedelta(days=1)
    return d


def _at(d, hour, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=BOGOTA)


def _iso(m):
    return m.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def ghl(monkeypatch):
    state = {"free": [], "events": [], "created": None, "sent": [], "asked_calendar": None}

    async def free_slots(token, calendar_id, start, end, tz="America/Bogota", **kw):
        state["asked_calendar"] = calendar_id
        return [_iso(m) for m in state["free"]]

    async def list_events(**kw):
        return {"events": state["events"]}

    async def upsert(token, location, **kw):
        return {"contact": {"id": "c1"}}

    async def create(**kw):
        state["created"] = kw
        return {"appointment": {"id": "evt1"}}

    async def send(token, sender, to, subject, html):
        state["sent"].append((to, subject))
        return {}

    async def token(*args, **kwargs):
        return "gmail-token"

    monkeypatch.setattr(endpoint, "get_settings", lambda: _Settings())
    monkeypatch.setattr(ghl_calendar, "get_available_slots", free_slots)
    monkeypatch.setattr(ghl_calendar, "list_events", list_events)
    monkeypatch.setattr(ghl_calendar, "upsert_contact", upsert)
    monkeypatch.setattr(ghl_calendar, "create_appointment", create)
    monkeypatch.setattr(ghl_calendar, "extract_appointment", lambda c: c["appointment"])
    monkeypatch.setattr(ghl_calendar, "get_meet_link", lambda c: None)
    monkeypatch.setattr(notifications, "get_access_token", token)
    monkeypatch.setattr(notifications, "send_email", send)
    monkeypatch.setattr(calendars_service.FtHours, "is_holiday", staticmethod(lambda y, m, d: False))
    return state


def _starts(body):
    return [s["start_co"][11:16] for s in body["available_slots"]]


def test_the_ghl_tools_are_mounted_next_to_the_google_ones():
    paths = {p.removeprefix("/api/v1/") for p in app.openapi()["paths"]}
    for tool in (
        "get-available-slots",
        "book-appointment",
        "find-appointment",
        "edit-appointment",
        "cancel-appointment",
    ):
        assert f"{tool}-ghl" in paths and f"{tool}-google" in paths


def test_ft_slots_use_the_ft_opening_hours_and_its_ghl_calendar(ghl):
    monday = _day(1)  # FT opens Mondays 07:00-12:00
    ghl["free"] = [_at(monday, 6, 30), _at(monday, 8), _at(monday, 11, 40), _at(monday, 13)]

    body = client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "FT"}).json()

    assert ghl["asked_calendar"] == "ft-cal"
    assert _starts(body) == ["08:00"]  # 11:40-12:10 ends after closing, 13:00 is outside the window


def test_a_configured_calendar_uses_the_default_hours_of_calendars_yaml(ghl):
    thursday = _day(4)  # FT is closed on Thursdays; the default hours for new calendars are Monday to Friday
    ghl["free"] = [_at(thursday, 9), _at(thursday, 12, 10)]

    body = client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "control"}).json()

    assert ghl["asked_calendar"] == "control-cal"
    assert _starts(body) == ["09:00"]  # 12:10 falls in the default lunch break
    assert body["available_slots"][0]["end_co"][11:16] == "09:20"  # CONTROL's duration

    closed = client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "FT"}).json()
    assert closed["available_slots"] == []


def test_booking_titles_the_appointment_and_notifies_the_team(ghl):
    monday = _day(1)
    start = _at(monday, 8)
    ghl["free"] = [start]

    body = client.post(
        "/api/v1/book-appointment-ghl",
        json={
            "contact_id": "c1",
            "calendar_type": "FT",
            "start_date": start.isoformat(),
            "contact_name": "ana gomez",
            "contact_email": "ana@gmail.com",
            "contact_phone": "+573000000000",
        },
    ).json()

    assert body["success"] is True and body["event_id"] == "evt1" and body["errors"] is None
    assert ghl["created"]["title"] == "First Visit - Ana Gomez - +573000000000"
    assert ghl["created"]["calendar_id"] == "ft-cal" and ghl["created"]["location_id"] == "loc"
    assert ghl["sent"] and ghl["sent"][0][0] == "team@example.org"


def test_booking_outside_the_ft_booking_hours_is_rejected(ghl):
    sunday = _day(7)
    start = _at(sunday, 9)
    ghl["free"] = [start]
    body = client.post(
        "/api/v1/book-appointment-ghl",
        json={
            "contact_id": "c1",
            "calendar_type": "FT",
            "start_date": start.isoformat(),
            "contact_name": "Ana",
            "contact_email": "a@gmail.com",
            "contact_phone": "1",
        },
    ).json()
    assert body["success"] is False and body["reason"] == "invalid_hour"
