from fastapi.testclient import TestClient

from tests.tools.apps import surrogacy_app as app

client = TestClient(app)

URL = "/api/v1/surrogate-classification"


def _payload(**overrides):
    payload = {
        "age": "28",
        "city": "Bogota",
        "nationality": "COL",
        "number_of_children": "2",
        "last_birth_date": "2020-01-15",
        "number_of_c_sections": "1",
        "abortions": "no",
        "preeclampsia": "no",
        "bmi": "22.5",
        "document_type": "cedula_ciudadania",
        "eps_active_affiliation": "yes",
        "drug_use": "no",
        "availability": "si",
    }
    payload.update(overrides)
    return payload


def test_surrogate_valid_payload_approved():
    """A valid payload is classified as approved."""
    response = client.post(URL, json=_payload())
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "result": "Approved",
        "eligibility_result": "approved",
        "not_eligibility_reason": "none",
        "errors": None,
    }


def test_surrogate_empty_payload_inconclusive():
    """An empty payload is classified as inconclusive."""
    body = client.post(URL, json={}).json()
    assert body["success"] is True
    assert body["result"] == "Inconclusive"
    assert body["not_eligibility_reason"] == "missing_data (age)"


def test_surrogate_three_c_sections_rejected():
    """Three C-sections are rejected."""
    body = client.post(URL, json=_payload(number_of_c_sections="3")).json()
    assert body["result"] == "Rejected (C-Sections)"
    assert body["not_eligibility_reason"] == "c_sections"


def test_surrogate_no_availability_rejected():
    """No time for appointments is rejected."""
    body = client.post(URL, json=_payload(availability="no")).json()
    assert body["result"] == "Rejected (Availability)"
    assert body["not_eligibility_reason"] == "availability"


def test_surrogate_voice_pre_approved_without_document_or_eps():
    """In a voice call the endpoint ignores the document and the EPS and answers pre-approved."""
    body = client.post(URL, json=_payload(voice="yes", document_type="", eps_active_affiliation="")).json()
    assert body == {
        "success": True,
        "result": "Pre-approved",
        "eligibility_result": "pre-approved",
        "not_eligibility_reason": "none",
        "errors": None,
    }


def test_surrogate_voice_ignores_a_rejecting_document_and_eps():
    """In a voice call a document or EPS that would reject outside voice does not reject."""
    body = client.post(URL, json=_payload(voice="true", document_type="pasaporte", eps_active_affiliation="no")).json()
    assert body["result"] == "Pre-approved" and body["eligibility_result"] == "pre-approved"


def test_surrogate_voice_off_is_approved_and_evaluates_the_document():
    """With voice off the answer is approved, and a missing document is still inconclusive."""
    assert client.post(URL, json=_payload(voice="no")).json()["eligibility_result"] == "approved"
    body = client.post(URL, json=_payload(voice="no", document_type="")).json()
    assert body["result"] == "Inconclusive" and body["not_eligibility_reason"] == "missing_data (document_type)"
