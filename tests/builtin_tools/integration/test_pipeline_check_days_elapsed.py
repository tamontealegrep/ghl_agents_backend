"""End-to-end tests of the check-days-elapsed endpoint, with no external dependencies."""

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


def test_elapsed_true_past_threshold():
    """A date older than the threshold is reported as elapsed."""
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


def test_elapsed_false_under_threshold():
    """A date newer than the threshold is not elapsed."""
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_days_ago(100), "days": 365},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is False


def test_elapsed_accepts_dash_dates():
    """Dates written as YYYY-MM-DD are accepted."""
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_dash_days_ago(400), "days": 365},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is True
    assert body["days_elapsed"] >= 400
    assert body["errors"] is None


def test_elapsed_supports_long_thresholds():
    """A 500-day threshold works like a short one."""
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_days_ago(600), "days": 500},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is True


def test_elapsed_rejects_bad_date_format():
    """A date in an unknown format returns an error naming the two valid formats."""
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": "15-06-2024", "days": 365},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is None
    assert "YYYY-MM-DD" in body["errors"] and "YYYY/MM/DD" in body["errors"]


def test_elapsed_rejects_missing_date():
    """A missing date returns the same format error."""
    response = client.post("/api/v1/check-days-elapsed", json={"days": 365})
    body = response.json()
    assert body["success"] is True
    assert "YYYY-MM-DD" in body["errors"] and "YYYY/MM/DD" in body["errors"]


def test_elapsed_rejects_zero_days():
    """A threshold of 0 days returns an error and no result."""
    response = client.post(
        "/api/v1/check-days-elapsed",
        json={"date": _ymd_days_ago(400), "days": 0},
    )
    body = response.json()
    assert body["success"] is True
    assert body["elapsed"] is None
    assert "greater than 0" in body["errors"]
