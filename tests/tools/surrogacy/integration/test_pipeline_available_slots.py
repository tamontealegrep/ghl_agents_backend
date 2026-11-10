"""Prueba el endpoint /available-slots de punta a punta con la llamada a Google mockeada."""

import pytest
from fastapi.testclient import TestClient

from surrogacy.api.v1.endpoints import get_available_slots as slots_endpoint
from tests.tools.apps import surrogacy_app as app

client = TestClient(app)


class _FakeSettings:
    google_client_id = "fake-client-id"
    google_client_secret = "fake-client-secret"
    google_refresh_token = "fake-refresh-token"
    calendar_id = "primary"
    duration_minutes = 30
    interval_minutes = 0
    pre_buffer_minutes = 0
    post_buffer_minutes = 0
    min_notice_minutes = None
    date_range_days = 14


_FakeSettings.calendars = {"FT": _FakeSettings}


class _EmptySettings(_FakeSettings):
    google_client_id = ""
    google_client_secret = ""
    google_refresh_token = ""


_EmptySettings.calendars = {"FT": _EmptySettings}


async def _fake_get_access_token(*args, **kwargs):
    return "fake-access-token"


async def _fake_get_free_busy_empty(*args, **kwargs):
    return []


@pytest.fixture
def mocked_google_calendar(monkeypatch):
    """Reemplaza Settings y las llamadas HTTP a Google por dobles deterministas."""
    monkeypatch.setattr(slots_endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(slots_endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(slots_endpoint, "get_free_busy", _fake_get_free_busy_empty)


def test_available_slots_endpoint_success_shape(mocked_google_calendar):
    response = client.post("/api/v1/get-available-slots", json={"iana_timezone": "America/Bogota", "calendar_type": "FT"})
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["iana_timezone"] == "America/Bogota"
    assert body["errors"] is None
    assert isinstance(body["available_slots"], list)
    for slot in body["available_slots"]:
        assert set(slot.keys()) == {"start_co", "end_co", "start_local", "end_local"}


def test_available_slots_endpoint_defaults_timezone_when_blank(mocked_google_calendar):
    response = client.post("/api/v1/get-available-slots", json={"iana_timezone": "   "})
    assert response.json()["iana_timezone"] == "America/Bogota"


def test_available_slots_endpoint_fails_gracefully_when_credentials_missing(monkeypatch):
    monkeypatch.setattr(slots_endpoint, "get_settings", lambda: _EmptySettings())

    response = client.post("/api/v1/get-available-slots", json={"calendar_type": "FT"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["available_slots"] == []
    assert "GOOGLE_CLIENT_ID" in body["errors"]


def test_available_slots_endpoint_fails_gracefully_when_google_api_errors(monkeypatch):
    monkeypatch.setattr(slots_endpoint, "get_settings", lambda: _FakeSettings())

    async def _raise(*args, **kwargs):
        raise RuntimeError("Google API unreachable")

    monkeypatch.setattr(slots_endpoint, "get_access_token", _raise)

    response = client.post("/api/v1/get-available-slots", json={"calendar_type": "FT"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "Google API unreachable" in body["errors"]

