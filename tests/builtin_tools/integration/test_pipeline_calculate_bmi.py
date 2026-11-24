"""
Prueba el endpoint /calculate-bmi de punta a punta. Sin dependencias externas.
"""

from fastapi.testclient import TestClient
from tests.builtin_tools.app_factory import app

client = TestClient(app)


def test_bmi_endpoint_succeeds():
    """The BMI endpoint returns the calculated BMI."""
    response = client.post("/api/v1/calculate-bmi", json={"weight_kg": 70, "height_cm": 175})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["bmi"] == 22.9
    assert body["errors"] is None


def test_bmi_endpoint_rejects_zero_height():
    """A zero height returns a business error, not an HTTP failure."""
    response = client.post("/api/v1/calculate-bmi", json={"weight_kg": 70, "height_cm": 0})
    body = response.json()
    assert body["success"] is True
    assert body["bmi"] is None
    assert "Valores invalidos" in body["errors"]


def test_bmi_endpoint_rejects_missing_fields():
    """Missing weight or height returns a business error, not an HTTP failure."""
    response = client.post("/api/v1/calculate-bmi", json={})
    body = response.json()
    assert body["success"] is True
    assert body["bmi"] is None
    assert "Valores invalidos" in body["errors"]
