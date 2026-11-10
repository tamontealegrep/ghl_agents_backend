"""The shared GoHighLevel scheduling tools, with a fake company and a fake GHL."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_backend import ghl_calendar, ghl_scheduling
from agent_backend.calendars import load_calendar_settings
from agent_backend.ghl_schedule import clear_cache
from agent_backend.ghl_scheduling import GhlSchedulingHooks, build_ghl_scheduling_router

BOGOTA = ZoneInfo("America/Bogota")


class Hours:
    def window(self, weekday, day):
        return (7, 0, 17, 0) if 1 <= weekday <= 5 else None

    def is_lunch(self, start, end):
        return start.hour * 60 + start.minute < 13 * 60 and end.hour * 60 + end.minute > 12 * 60

    def is_holiday(self, year, month, day):
        return False


class Booking:
    EVENT_TITLE_PREFIX = "Visit"
    TITLE_SEPARATOR = " - "

    @staticmethod
    def parse_start_date(raw):
        parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=BOGOTA)

    @staticmethod
    def parse_duration_minutes(raw, default=10):
        return int(raw) if raw and raw.strip().isdigit() else default

    @staticmethod
    def format_contact_name(raw):
        return " ".join(w.capitalize() for w in raw.split())

    @staticmethod
    def is_valid_business_hour(weekday, hour, minute):
        return 1 <= weekday <= 5 and 7 <= hour < 17


class Cal:
    key = "FT"
    booking = Booking()
    hours = Hours()

    def __init__(self, tool):
        self.tool = tool


GHL_CALENDAR = {
    "slotDuration": 30, "slotDurationUnit": "mins", "slotInterval": 10, "slotIntervalUnit": "mins",
    "preBuffer": None, "slotBuffer": 15, "slotBufferUnit": "mins",
    "allowBookingAfter": 0, "allowBookingAfterUnit": "days", "allowBookingFor": 14, "allowBookingForUnit": "days",
}


class Env:
    """Everything a test can change; the hooks read it at call time."""

    def __init__(self):
        self.env = {"XX_GHL_CALENDAR_ID_FT": "cal1"}
        self.token = "token"
        self.location = "loc1"
        self.notified = []
        self.notify_result = None
        self.calendar = dict(GHL_CALENDAR)

    @property
    def settings(self):
        class S:
            ghl_token = self.token
            ghl_location_id = self.location

        return S()

    def tool(self):
        return load_calendar_settings("XX", "FT", read_unset_from_ghl=True, environ=self.env)


@pytest.fixture
def world(monkeypatch):
    clear_cache()
    w = Env()

    async def notify(settings, policy, **kwargs):
        w.notified.append(kwargs)
        return w.notify_result

    hooks = GhlSchedulingHooks(
        prefix="XX",
        get_settings=lambda: w.settings,
        resolve_calendar=lambda settings, ct: Cal(w.tool()) if (ct or "").upper() == "FT" else None,
        unknown_calendar_message=lambda settings, ct: f"Unknown calendar_type '{ct}'. Valid values: FT",
        default_earliest=lambda now: now + timedelta(days=1),
        notify_booking=notify,
        business_tz="America/Bogota",
    )
    app = FastAPI()
    app.include_router(build_ghl_scheduling_router(hooks))
    w.client = TestClient(app)
    w.calls = {}

    async def get_calendar(token, calendar_id, **kw):
        w.calls["get_calendar"] = w.calls.get("get_calendar", 0) + 1
        return {"calendar": w.calendar}

    monkeypatch.setattr(ghl_calendar, "get_calendar", get_calendar)
    w.free, w.events, w.appointment = [], [], {"id": "evt1"}

    async def free_slots(token, calendar_id, start, end, tz="America/Bogota", **kw):
        w.calls["free"] = {"start": start, "end": end, "kw": kw}
        return [iso(m) for m in w.free]

    async def list_events(**kw):
        w.calls["list_events"] = w.calls.get("list_events", 0) + 1
        return {"events": w.events}

    async def upsert(token, location, **kw):
        w.calls["upsert"] = kw
        return {"contact": {"id": "c1"}}

    async def create(**kw):
        w.calls["create"] = kw
        if getattr(w, "create_error", None):
            raise w.create_error
        return {"appointment": w.appointment}

    async def update(**kw):
        w.calls["update"] = kw
        return {"id": kw["appointment_id"]}

    async def delete(token, appointment_id, **kw):
        w.calls["delete"] = appointment_id
        return True

    monkeypatch.setattr(ghl_calendar, "get_available_slots", free_slots)
    monkeypatch.setattr(ghl_calendar, "list_events", list_events)
    monkeypatch.setattr(ghl_calendar, "upsert_contact", upsert)
    monkeypatch.setattr(ghl_calendar, "create_appointment", create)
    monkeypatch.setattr(ghl_calendar, "update_appointment", update)
    monkeypatch.setattr(ghl_calendar, "delete_appointment", delete)
    monkeypatch.setattr(ghl_calendar, "extract_appointment", lambda created: created.get("appointment", created))
    monkeypatch.setattr(ghl_calendar, "get_meet_link", lambda created: None)
    return w


def day(iso_weekday=4, min_days=10):
    d = datetime.now(BOGOTA).date() + timedelta(days=min_days)
    while d.isoweekday() != iso_weekday:
        d += timedelta(days=1)
    return d


def at(d, hour, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=BOGOTA)


def iso(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def event(start, end, event_id="e1", **extra):
    return {"id": event_id, "startTime": iso(start), "endTime": iso(end), **extra}


def starts(body):
    return [s["start_co"][11:16] for s in body["available_slots"]]


# --------------------------------------------------------------------------- common


def test_calendar_type_is_required_and_unknown_values_are_rejected(world):
    for tool in ("get-available-slots-ghl", "find-appointment-ghl", "cancel-appointment-ghl"):
        body = world.client.post(f"/{tool}", json={"event_id": "e", "contact_name": "Ana"}).json()
        assert body["success"] is False and "Unknown calendar_type" in body["errors"], tool


@pytest.mark.parametrize(
    ("attr", "value", "expected"),
    [("token", "", "GHL_TOKEN"), ("location", "", "GHL_LOCATION_ID")],
)
def test_missing_company_configuration_is_named(world, attr, value, expected):
    setattr(world, attr, value)
    body = world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"}).json()
    assert body["success"] is False and expected in body["errors"]


def test_missing_calendar_id_names_the_variable(world):
    world.env = {"XX_DURATION_MINUTES_FT": "30"}
    body = world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"}).json()
    assert "XX_GHL_CALENDAR_ID_FT" in body["errors"]


# --------------------------------------------------------------------------- slots


def test_slots_take_buffers_from_the_ghl_calendar_and_drop_slots_inside_them(world):
    d = day()
    world.free = [at(d, 9, 30), at(d, 9, 40), at(d, 10, 0)]
    world.events = [event(at(d, 9, 0), at(d, 9, 30))]

    body = world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"}).json()

    # GHL's post buffer is 15 minutes: 09:30 and 09:40 are inside 09:30-09:45, 10:00 is free.
    assert starts(body) == ["10:00"]
    assert world.calls["get_calendar"] == 1


def test_duration_is_not_sent_when_it_comes_from_ghl_and_is_sent_when_it_is_in_the_env(world):
    d = day()
    world.free = [at(d, 9)]
    world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"})
    assert world.calls["free"]["kw"]["duration_minutes"] is None

    world.env["XX_DURATION_MINUTES_FT"] = "20"
    body = world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"}).json()
    assert world.calls["free"]["kw"]["duration_minutes"] == 20
    assert body["available_slots"][0]["end_co"][11:16] == "09:20"


def test_slots_outside_opening_hours_or_in_lunch_are_dropped(world):
    d = day()
    # 11:30-12:00 ends when lunch starts (offered); 11:40-12:10 overlaps it (dropped); 12:50-13:20 overlaps its end.
    world.free = [at(d, 6, 30), at(d, 9), at(d, 11, 30), at(d, 11, 40), at(d, 12, 10), at(d, 12, 50), at(d, 13), at(d, 17), at(day(6), 9)]
    world.env["XX_POST_BUFFER_MINUTES_FT"] = "0"
    body = world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"}).json()
    assert starts(body) == ["09:00", "11:30", "13:00"]


def test_interval_from_the_env_thins_the_slots(world):
    d = day()
    world.free = [at(d, 9, m) for m in (0, 10, 20, 30, 40)]
    world.env["XX_INTERVAL_MINUTES_FT"] = "30"
    world.env["XX_POST_BUFFER_MINUTES_FT"] = "0"
    assert starts(world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"}).json()) == ["09:00", "09:30"]


def test_min_notice_from_ghl_sets_the_search_start(world):
    world.calendar["allowBookingAfter"] = 3
    world.calendar["allowBookingAfterUnit"] = "days"
    world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"})
    asked = world.calls["free"]["start"]
    assert abs((asked - datetime.now(UTC) - timedelta(days=3)).total_seconds()) < 60


def test_a_date_range_over_ghls_limit_in_the_env_is_rejected(world):
    world.env["XX_DATE_RANGE_DAYS_FT"] = "45"
    body = world.client.post("/get-available-slots-ghl", json={"calendar_type": "FT"}).json()
    assert "XX_DATE_RANGE_DAYS_FT" in body["errors"] and "31" in body["errors"]


# --------------------------------------------------------------------------- book


def book(world, start, **overrides):
    payload = {
        "calendar_type": "FT", "start_date": start.isoformat(), "duration": "99",
        "contact_name": "ana gomez", "contact_email": "Ana@Gmail.com", "contact_phone": "+573000000000",
    }
    payload.update(overrides)
    return world.client.post("/book-appointment-ghl", json=payload).json()


def test_booking_creates_the_appointment_with_the_calendars_duration_and_notifies_the_team(world):
    start = at(day(), 9)
    world.free = [start]

    body = book(world, start)

    assert body["success"] is True and body["event_id"] == "evt1" and body["errors"] is None
    created = world.calls["create"]
    assert created["title"] == "Visit - Ana Gomez - +573000000000"
    assert (created["end_dt"] - created["start_dt"]) == timedelta(minutes=30)  # GHL's duration, not the request's "99"
    assert created["appointment_status"] == "confirmed" and created["to_notify"] is False
    assert world.calls["upsert"]["email"] == "ana@gmail.com"
    assert world.notified and world.notified[0]["contact_name"] == "Ana Gomez"


def test_a_notification_problem_does_not_fail_the_booking(world):
    start = at(day(), 9)
    world.free = [start]
    world.notify_result = "notification failed"
    body = book(world, start)
    assert body["success"] is True and body["errors"] == "notification failed"


@pytest.mark.parametrize(
    ("start", "reason"),
    [
        (lambda: at(day(), 9) - timedelta(days=60), "past_date"),
        (lambda: at(day(), 20), "invalid_hour"),
        (lambda: at(day(6), 9), "invalid_hour"),
        (lambda: at(day(min_days=40), 9), "invalid_hour"),  # beyond the booking window
    ],
)
def test_booking_rejections_by_date_and_hours(world, start, reason):
    body = book(world, start())
    assert body["success"] is False and body["reason"] == reason


def test_booking_a_time_ghl_does_not_offer_is_slot_taken(world):
    start = at(day(), 9)
    world.free = [at(day(), 10)]
    assert book(world, start)["reason"] == "slot_taken"


def test_booking_is_refused_inside_the_buffer_of_another_appointment(world):
    d = day()
    start = at(d, 9, 40)
    world.free = [start]  # GHL still lists it (e.g. its buffer is not configured)
    world.events = [event(at(d, 9, 0), at(d, 9, 30))]
    assert book(world, start)["reason"] == "slot_taken"


def test_booking_needs_an_email_or_a_phone(world):
    start = at(day(), 9)
    world.free = [start]
    body = book(world, start, contact_email="", contact_phone="")
    assert body["success"] is False and "required" in body["errors"]


def test_a_ghl_400_is_reported_as_slot_taken_with_its_message(world):
    start = at(day(), 9)
    world.free = [start]
    request = httpx.Request("POST", "https://x")
    world.create_error = httpx.HTTPStatusError("bad", request=request, response=httpx.Response(400, request=request, json={"message": "slot unavailable"}))
    body = book(world, start)
    assert body["reason"] == "slot_taken" and "slot unavailable" in body["errors"]


# --------------------------------------------------------------------------- find / edit / cancel


def test_find_matches_by_contact_id_title_and_skips_cancelled(world):
    d = day()
    world.events = [
        event(at(d, 9), at(d, 9, 30), "by_contact", title="Whatever", contactId="c1"),
        event(at(d, 10), at(d, 10, 30), "by_title", title="Visit - Ana Gomez - +57300"),
        event(at(d, 11), at(d, 11, 30), "cancelled", title="Visit - Ana Gomez", appointmentStatus="cancelled"),
        event(at(d, 12), at(d, 12, 30), "other", title="Visit - Luis Ruiz"),
    ]
    body = world.client.post("/find-appointment-ghl", json={"calendar_type": "FT", "contact_name": "Ana Gomez", "contact_email": "ana@gmail.com"}).json()
    assert body["success"] is True
    assert [a["event_id"] for a in body["appointments"]] == ["by_contact", "by_title"]


def test_find_by_phone_digits_in_the_title(world):
    d = day()
    world.events = [event(at(d, 9), at(d, 9, 30), "x", title="Visit - Ana - +57 300 123 4567")]
    body = world.client.post("/find-appointment-ghl", json={"calendar_type": "FT", "contact_phone": "3001234567"}).json()
    assert [a["event_id"] for a in body["appointments"]] == ["x"]


def test_find_validates_its_input_and_reports_no_results(world):
    assert "at least" in world.client.post("/find-appointment-ghl", json={"calendar_type": "FT"}).json()["errors"]
    assert "not in a valid format" in world.client.post("/find-appointment-ghl", json={"calendar_type": "FT", "contact_email": "nope"}).json()["errors"]
    assert "No appointments found" in world.client.post("/find-appointment-ghl", json={"calendar_type": "FT", "contact_name": "Nadie Aqui"}).json()["errors"]


def test_edit_moves_the_appointment_but_not_into_another_ones_buffer(world):
    d = day()
    world.events = [event(at(d, 9), at(d, 9, 30), "other"), event(at(d, 14), at(d, 14, 30), "mine")]
    refused = world.client.post("/edit-appointment-ghl", json={"calendar_type": "FT", "event_id": "mine", "new_start_date": at(d, 9, 40).isoformat()}).json()
    assert refused["success"] is False and "already taken" in refused["errors"]

    ok = world.client.post("/edit-appointment-ghl", json={"calendar_type": "FT", "event_id": "mine", "new_start_date": at(d, 10).isoformat()}).json()
    assert ok["success"] is True and "rescheduled" in ok["message"] and ok["new_duration"] == "30"
    assert world.calls["update"]["appointment_id"] == "mine"
    assert world.calls["update"]["end_dt"] - world.calls["update"]["start_dt"] == timedelta(minutes=30)


def test_cancel_deletes_the_appointment(world):
    body = world.client.post("/cancel-appointment-ghl", json={"calendar_type": "FT", "event_id": "evt9"}).json()
    assert body["success"] is True and world.calls["delete"] == "evt9"


def test_the_shared_module_has_no_company_specific_name():
    source = open(ghl_scheduling.__file__, encoding="utf-8").read().lower()
    assert "babynova" not in source and "family aims" not in source and "family_aims" not in source
