from fastapi.testclient import TestClient
from tests.tools.apps import desk_app as app

client = TestClient(app)

def test_check_visa_endpoint():
    # El app standalone tiene el prefijo /api/v1 definido en su main.py
    response = client.post("/api/v1/check-visa", json={"nationalities": "USA"})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["nationality"] == "USA"
    assert data["requires_visa"] is False
    assert data["conditional_visa"] is False
    assert data["errors"] is None

def test_check_visa_endpoint_multiple():
    response = client.post("/api/v1/check-visa", json={"nationalities": "  China , India  "})
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["nationality"] == "China, India"
    assert data["requires_visa"] is True
    assert data["conditional_visa"] is True
