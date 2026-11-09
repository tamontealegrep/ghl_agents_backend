"""
Prueba el endpoint /available-slots-ivf de punta a punta con Google Calendar mockeado.
"""

import pytest
from fastapi.testclient import TestClient

from family_aims.api.v1.endpoints import get_available_slots_google as endpoint
from tests.tools.apps import family_aims_app as app

client = TestClient(app)


class _FakeCreds:
    google_client_id = "fake-client-id"
    google_client_secret = "fake-client-secret"
    google_refresh_token = "fake-refresh-token"
    calendar_id = "achuquisan@familyaims.com"
    duration_minutes = 20
    interval_minutes = 10
    date_range_days = 7


class _EmptyCreds(_FakeCreds):
    google_client_id = ""
    google_client_secret = ""
    google_refresh_token = ""


class _FakeSettings:
    ivf = _FakeCreds()
    calendars = {"IVF": ivf}


class _EmptySettings:
    ivf = _EmptyCreds()
    calendars = {"IVF": ivf}


async def _fake_get_access_token(*args, **kwargs):
    return "fake-access-token"


async def _fake_get_free_busy_empty(*args, **kwargs):
    return []


@pytest.fixture
def mocked_google_calendar(monkeypatch):
    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(endpoint, "get_access_token", _fake_get_access_token)
    monkeypatch.setattr(endpoint, "get_free_busy", _fake_get_free_busy_empty)


def test_available_slots_ivf_endpoint_success_shape(mocked_google_calendar):
    response = client.post("/api/v1/get-available-slots-google", json={"iana_timezone": "America/Bogota", "calendar_type": "IVF"})
    assert response.status_code == 200

    body = response.json()
    assert body["success"] is True
    assert body["iana_timezone"] == "America/Bogota"
    assert body["errors"] is None
    assert isinstance(body["available_slots"], list)
    for slot in body["available_slots"]:
        assert set(slot.keys()) == {"start_co", "end_co", "start_local", "end_local"}


def test_available_slots_ivf_endpoint_fails_gracefully_when_credentials_missing(monkeypatch):
    monkeypatch.setattr(endpoint, "get_settings", lambda: _EmptySettings())

    response = client.post("/api/v1/get-available-slots-google", json={"calendar_type": "IVF"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["available_slots"] == []
    assert "GOOGLE_CLIENT_ID_IVF" in body["errors"]


def test_available_slots_ivf_endpoint_fails_gracefully_when_google_api_errors(monkeypatch):
    monkeypatch.setattr(endpoint, "get_settings", lambda: _FakeSettings())

    async def _raise(*args, **kwargs):
        raise RuntimeError("Google API unreachable")

    monkeypatch.setattr(endpoint, "get_access_token", _raise)

    response = client.post("/api/v1/get-available-slots-google", json={"calendar_type": "IVF"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert "Google API unreachable" in body["errors"]
