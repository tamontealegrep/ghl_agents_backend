"""Family Aims serves contacts from all over the world: ``days`` is the summary in the contact's own time zone."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from desk.api.v1.endpoints import get_available_slots_ghl as endpoint
from fastapi.testclient import TestClient

from tests.tools.apps import desk_app as app

client = TestClient(app)
BOGOTA = ZoneInfo("America/Bogota")


class _Tool:
    ghl_calendar_id = "cal"
    duration_minutes = 30
    interval_minutes = 0
    pre_buffer_minutes = 0
    post_buffer_minutes = 0
    min_notice_minutes = None
    date_range_days = 14


class _Settings:
    ghl_token = "token"
    ivf = _Tool()
    calendars = {"IVF": ivf}


def _monday():
    day = datetime.now(BOGOTA).date() + timedelta(days=10)
    while day.isoweekday() != 1:  # IVF opens on Mondays, 07:00 to 12:00 in Bogota
        day += timedelta(days=1)
    return day


@pytest.fixture
def free_monday(monkeypatch):
    monday = _monday()
    # 08:00, 08:30 and 09:00 in Bogota, as GHL returns them (UTC)
    starts = [f"{monday.isoformat()}T{h:02d}:{m:02d}:00Z" for h, m in ((13, 0), (13, 30), (14, 0))]

    async def _free(**kwargs):
        return starts

    monkeypatch.setattr(endpoint, "get_settings", lambda: _Settings())
    monkeypatch.setattr(endpoint, "ghl_get_available_slots", _free)
    monkeypatch.setattr(endpoint, "is_holiday", lambda y, m, d: False)
    return monday


def _post(tz):
    return client.post("/api/v1/get-available-slots-ghl", json={"calendar_type": "IVF", "iana_timezone": tz}).json()


def test_days_come_before_the_slots_and_slots_have_no_end(free_monday):
    """The response lists days first, and a slot only carries its start."""
    body = _post("America/Bogota")

    assert list(body)[:4] == ["success", "iana_timezone", "days", "available_slots"]
    assert set(body["available_slots"][0]) == {"start_co", "start_local"}
    day = body["days"][0]
    assert day["date"] == free_monday.isoformat()
    assert day["timezone"] == "America/Bogota" and day["utc_offset"] == "-05:00"
    assert day["parts_of_day"] == ["morning"] and day["slot_count"] == 3
    assert day["times"] == [{"type": "continuous_range", "first_start": "08:00", "last_start": "09:00", "every_minutes": 30}]


@pytest.mark.parametrize(
    ("tz", "parts"),
    [
        ("America/Los_Angeles", ["morning", "night"]),  # 05:00, 05:30 and 06:00 local
        ("Europe/Madrid", ["afternoon"]),
        ("Asia/Tokyo", ["night"]),  # 22:00 to 23:00 local
        ("Australia/Sydney", ["night"]),  # 00:00 to 01:00 of the next calendar day
    ],
)
def test_days_follow_the_contacts_zone_everywhere(free_monday, tz, parts):
    """Date, offset and part of the day are the contact's, for zones far from Bogota too."""
    body = _post(tz)
    day = body["days"][0]
    first_local = datetime.fromisoformat(body["available_slots"][0]["start_local"])

    assert day["timezone"] == tz
    assert day["date"] == first_local.date().isoformat()  # may be the next calendar day for east zones
    assert day["utc_offset"] == first_local.strftime("%z")[:3] + ":" + first_local.strftime("%z")[3:]
    assert sum(d["slot_count"] for d in body["days"]) == len(body["available_slots"]) == 3
    assert day["parts_of_day"] == parts
