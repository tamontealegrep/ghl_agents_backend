"""
Prueba el endpoint /request-callback de punta a punta. Sin dependencias externas.
"""

from fastapi.testclient import TestClient

from tests.builtin_tools.app_factory import app

client = TestClient(app)


def test_callback_request_success_minimal():
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "no_availability",
            "timezone": "America/Bogota",
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


def test_callback_request_success_with_email_only_and_full_preferences():
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "John Smith",
            "contact_email": "john@example.com",
            "reason": "user_requested",
            "context": "Prefiere que lo llamen por la tarde",
            "preferred_days": ["monday", "wednesday"],
            "preferred_time_window": "afternoon",
            "timezone": "Europe/Madrid",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert body["contact_phone"] is None
    assert body["contact_email"] == "john@example.com"
    assert body["preferred_days"] == ["monday", "wednesday"]
    assert body["preferred_time_window"] == "afternoon"
    assert body["timezone"] == "Europe/Madrid"


def test_callback_request_weekdays_shortcut():
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "booking_failed",
            "preferred_days": "weekdays",
            "timezone": "America/Bogota",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert body["preferred_days"] == ["monday", "tuesday", "wednesday", "thursday", "friday"]


def test_callback_request_missing_contact_info_returns_error_not_failure():
    response = client.post(
        "/api/v1/callback",
        json={"contact_name": "Maria Perez", "reason": "no_availability", "timezone": "America/Bogota"},
    )
    body = response.json()
    assert body["success"] is True
    assert "contact_phone" in body["errors"]


def test_callback_request_invalid_reason_returns_error_not_failure():
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "quiero_hablar_con_alguien",
            "timezone": "America/Bogota",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert "reason" in body["errors"]


def test_callback_request_invalid_timezone_returns_error_not_failure():
    response = client.post(
        "/api/v1/callback",
        json={
            "contact_name": "Maria Perez",
            "contact_phone": "+573001234567",
            "reason": "no_availability",
            "timezone": "Colombia/Bogota",
        },
    )
    body = response.json()
    assert body["success"] is True
    assert "timezone" in body["errors"]


def test_callback_request_missing_fields_defaults_to_empty():
    response = client.post("/api/v1/callback", json={})
    body = response.json()
    assert body["success"] is True
    assert "contact_name" in body["errors"]
