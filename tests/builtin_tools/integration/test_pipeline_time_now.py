from fastapi.testclient import TestClient

from tests.builtin_tools.app_factory import app

client = TestClient(app)


def test_time_now_endpoint_success_shape():
    response = client.post("/api/v1/time-now", json={"iana_timezone": "America/Bogota"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["iana_timezone"] == "America/Bogota"
    assert body["now"].endswith("-05:00")
    assert body["errors"] is None


def test_time_now_endpoint_defaults_to_utc_when_blank():
    response = client.post("/api/v1/time-now", json={"iana_timezone": "  "})
    body = response.json()
    assert body["iana_timezone"] == "UTC"


def test_time_now_endpoint_fails_gracefully_on_invalid_timezone():
    response = client.post("/api/v1/time-now", json={"iana_timezone": "No/Existe"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["now"] is None
    assert body["errors"]
