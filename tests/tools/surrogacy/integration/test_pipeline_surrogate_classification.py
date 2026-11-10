from fastapi.testclient import TestClient

from tests.tools.apps import surrogacy_app as app

client = TestClient(app)

URL = "/api/v1/surrogate-classification"


def _payload(**overrides):
    payload = {
        "age": "28", "city": "Bogota", "nationality": "COL", "number_of_children": "2",
        "last_birth_date": "2020-01-15", "number_of_c_sections": "1",
        "abortions": "no", "preeclampsia": "no", "bmi": "22.5",
        "document_type": "cedula_ciudadania", "drug_use": "no", "availability": "si",
    }
    payload.update(overrides)
    return payload


def test_v2_endpoint_returns_approved_for_valid_payload():
    response = client.post(URL, json=_payload())
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "result": "Approved",
        "eligibility_result": "approved",
        "eligibility_reason": "none",
        "errors": None,
    }


def test_v2_endpoint_returns_inconclusive_for_empty_payload():
    body = client.post(URL, json={}).json()
    assert body["success"] is True
    assert body["result"] == "Inconclusive"
    assert body["eligibility_reason"] == "missing_data (age)"


def test_v2_endpoint_rejects_three_c_sections():
    body = client.post(URL, json=_payload(number_of_c_sections="3")).json()
    assert body["result"] == "Rejected (C-Sections)"
    assert body["eligibility_reason"] == "c_sections"


def test_v2_endpoint_rejects_when_there_is_no_time_for_appointments():
    body = client.post(URL, json=_payload(availability="no")).json()
    assert body["result"] == "Rejected (Availability)"
    assert body["eligibility_reason"] == "availability"
