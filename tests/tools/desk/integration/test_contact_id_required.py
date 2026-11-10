"""Family Aims: booking and finding in GHL need the conversation's contact_id; they never look a contact up."""

import pytest
from desk.api.v1.endpoints import book_appointment_ghl as book_endpoint
from desk.api.v1.endpoints import find_appointment_ghl as find_endpoint
from fastapi.testclient import TestClient

from tests.tools.apps import desk_app as app

client = TestClient(app)


class _Tool:
    ghl_calendar_id = "cal"
    calendar_id = ""


class _Settings:
    gmail = None
    ghl_token = "token"
    ghl_location_id = "loc"
    calendars = {"IVF": _Tool()}


@pytest.fixture
def guarded(monkeypatch):
    """Any call to GHL fails the test: without a contact_id the tools must answer before reaching it."""
    calls = []

    async def forbidden(**kwargs):
        calls.append(kwargs)
        raise AssertionError("GHL must not be called without a contact_id")

    monkeypatch.setattr(book_endpoint, "get_settings", lambda: _Settings())
    monkeypatch.setattr(find_endpoint, "get_settings", lambda: _Settings())
    monkeypatch.setattr(book_endpoint, "ghl_get_available_slots", forbidden)
    monkeypatch.setattr(book_endpoint, "ghl_list_events", forbidden)
    monkeypatch.setattr(find_endpoint, "ghl_list_events", forbidden)
    return calls


BOOK = {
    "calendar_type": "IVF",
    "start_date": "2030-01-07T15:00:00Z",
    "duration": "20",
    "contact_name": "Ana Perez",
    "contact_email": "ana.perez@gmail.com",
    "contact_phone": "+570000000",
    "language": "ES",
    "iana_timezone": "America/Bogota",
}


@pytest.mark.parametrize("extra", [{}, {"contact_id": ""}, {"contact_id": "   "}])
def test_booking_fails_without_a_contact_id(guarded, extra):
    body = client.post("/api/v1/book-appointment-ghl", json={**BOOK, **extra}).json()

    assert body["success"] is False and body["reason"] == "missing_contact_id"
    assert "contact_id is required" in body["errors"]
    assert guarded == []


@pytest.mark.parametrize("extra", [{}, {"contact_id": ""}, {"contact_id": "   "}])
def test_finding_fails_without_a_contact_id(guarded, extra):
    payload = {"calendar_type": "IVF", "contact_name": "Ana Perez", "contact_email": "ana@gmail.com", **extra}

    body = client.post("/api/v1/find-appointment-ghl", json=payload).json()

    assert body["success"] is False and "contact_id is required" in body["errors"]
    assert guarded == []
