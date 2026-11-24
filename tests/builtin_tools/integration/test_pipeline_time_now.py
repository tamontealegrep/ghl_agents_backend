from fastapi.testclient import TestClient
from tests.builtin_tools.app_factory import app

client = TestClient(app)


def test_time_now_returns_expected_shape():
    """The time endpoint returns the time, the timezone and a calendar."""
    response = client.post("/api/v1/time-now", json={"iana_timezone": "America/Bogota"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["iana_timezone"] == "America/Bogota"
    assert body["now"].endswith("-05:00")
    assert body["errors"] is None


def test_time_now_blank_timezone_is_utc():
    """A blank timezone defaults to UTC."""
    response = client.post("/api/v1/time-now", json={"iana_timezone": "  "})
    body = response.json()
    assert body["iana_timezone"] == "UTC"


def test_time_now_invalid_timezone_is_graceful():
    """An invalid timezone returns an error in the body, not an HTTP failure."""
    response = client.post("/api/v1/time-now", json={"iana_timezone": "No/Existe"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["now"] is None
    assert body["errors"]
