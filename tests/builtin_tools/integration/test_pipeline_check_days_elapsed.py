"""
Prueba el endpoint /check-days-elapsed de punta a punta. Sin dependencias externas.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from tests.builtin_tools.app_factory import app

client = TestClient(app)


def _ymd_days_ago(n: int) -> str:
    d = (datetime.now(ZoneInfo("UTC")) - timedelta(days=n)).date()
    return f"{d.year:04d}/{d.month:02d}/{d.day:02d}"


def _ymd_dash_days_ago(n: int) -> str:
    d = (datetime.now(ZoneInfo("UTC")) - timedelta(days=n)).date()
    return f"{d.year:04d}-{d.month:02d}-{d.day:02d}"


def test_check_days_elapsed_true_when_past_threshold():
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_days_ago(400), "days": 365},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is True
    assert body["days_elapsed"] >= 400
    assert body["errors"] is None


def test_check_days_elapsed_false_when_under_threshold():
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_days_ago(100), "days": 365},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is False


def test_check_days_elapsed_accepts_dash_date_format():
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_dash_days_ago(400), "days": 365},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is True
    assert body["days_elapsed"] >= 400
    assert body["errors"] is None


def test_check_days_elapsed_supports_500_day_threshold():
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_days_ago(600), "days": 500},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is True


def test_check_days_elapsed_invalid_date_format():
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": "15-06-2024", "days": 365},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is None
    assert "YYYY-MM-DD" in body["errors"] and "YYYY/MM/DD" in body["errors"]


def test_check_days_elapsed_missing_date():
    response = client.post("/api/v1/check-days-elapsed", json={"days": 365})
    body = response.json()
    assert body["success"] is True
    assert "YYYY-MM-DD" in body["errors"] and "YYYY/MM/DD" in body["errors"]


def test_check_days_elapsed_invalid_days_threshold():
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_days_ago(400), "days": 0},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is None
    assert "mayor que 0" in body["errors"]
