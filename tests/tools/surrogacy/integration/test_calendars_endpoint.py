from fastapi.testclient import TestClient
from surrogacy.core import config as endpoint

from agent_backend.calendars import CalendarSettings
from tests.tools.apps import surrogacy_app as app

client = TestClient(app)


def test_calendars_lists_keys_and_integrations_without_ids(monkeypatch):
    class _Settings:
        calendars = {
            "FT": CalendarSettings("", "", "", "primary", ""),
            "CONTROL": CalendarSettings("", "", "", "", "secret-calendar-id"),
        }

    monkeypatch.setattr(endpoint, "get_settings", lambda: _Settings())

    body = client.get("/api/v1/calendars").json()

    assert body["calendars"] == [
        {"key": "FT", "ghl": False, "google": True},
        {"key": "CONTROL", "ghl": True, "google": False},
    ]
    assert "secret-calendar-id" not in str(body)
