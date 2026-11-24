"""End-to-end tests of the callback endpoint, with no external dependencies."""

from fastapi.testclient import TestClient
from tests.builtin_tools.app_factory import app

client = TestClient(app)


def test_callback_minimal_request_succeeds():
    """A name, phone, reason and timezone are enough for a valid callback."""
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "no_availability",
            "iana_timezone": "America/Bogota",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["contact_name"] == "Maria Perez"
    assert body["contact_phone"] == "+573001234567"
    assert body["contact_email"] is None
    assert body["preferred_days"] == []
    assert body["preferred_time_window"] is None
    assert body["errors"] is None


def test_callback_email_and_preferences_succeed():
    """An email-only request with days and time window is returned normalised."""
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "John Smith",
            "contact_email": "john@example.com",
            "reason": "user_requested",
            "context": "Prefiere que lo llamen por la tarde",
            "preferred_days": ["monday", "wednesday"],
            "preferred_time_window": "afternoon",
            "iana_timezone": "Europe/Madrid",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert body["contact_phone"] is None
    assert body["contact_email"] == "john@example.com"
    assert body["preferred_days"] == ["monday", "wednesday"]
    assert body["preferred_time_window"] == "afternoon"
    assert body["iana_timezone"] == "Europe/Madrid"


def test_callback_weekdays_shortcut_expands():
    """`weekdays` expands to Monday through Friday."""
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "booking_failed",
            "preferred_days": "weekdays",
            "iana_timezone": "America/Bogota",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert body["preferred_days"] == ["monday", "tuesday", "wednesday", "thursday", "friday"]


def test_callback_missing_contact_returns_error():
    """No phone and no email is a business error, not an HTTP failure."""
    response = client.post(
        "/api/v1/callback",
        json={"contact_name": "Maria Perez", "reason": "no_availability", "iana_timezone": "America/Bogota"},
    )
    body = response.json()
    assert body["success"] is True
    assert "contact_phone" in body["errors"]


def test_callback_invalid_reason_returns_error():
    """An unknown reason is a business error, not an HTTP failure."""
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "quiero_hablar_con_alguien",
            "iana_timezone": "America/Bogota",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert "reason" in body["errors"]


def test_callback_invalid_timezone_returns_error():
    """An unknown timezone is a business error, not an HTTP failure."""
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "no_availability",
            "iana_timezone": "Colombia/Bogota",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert "timezone" in body["errors"]


def test_callback_empty_body_returns_error():
    """An empty body is a business error asking for the contact name."""
    response = client.post("/api/v1/callback", json={})
    body = response.json()
    assert body["success"] is True
    assert "contact_name" in body["errors"]
