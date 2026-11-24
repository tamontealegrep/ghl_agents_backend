from fastapi.testclient import TestClient

from tests.tools.apps import surrogacy_app as app

client = TestClient(app)

URL = "/api/v1/donor-classification"


def _payload(**overrides):
    payload = {
        "age": "25",
        "city": "Bogota",
        "nationality": "COL",
        "sexual_life": "si",
        "height_cm": "165",
        "bmi": "22.0",
        "drug_use": "no",
        "pregnancies": "no",
        "abortions": "no",
        "lactating": "no",
        "document_type": "cedula_ciudadania",
        "eps_active_affiliation": "si",
    }
    payload.update(overrides)
    return payload


def test_donor_valid_payload_eligible():
    """A valid payload is classified as eligible."""
    response = client.post(URL, json=_payload())
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "result": "Approved",
        "eligibility_result": "eligible",
        "not_eligibility_reason": "none",
        "errors": None,
    }


def test_donor_empty_payload_incomplete():
    """An empty payload is classified as incomplete."""
    body = client.post(URL, json={}).json()
    assert body["success"] is True
    assert body["result"] == "Inconclusive"
    assert body["eligibility_result"] == "incomplete"
    assert body["not_eligibility_reason"] == "missing_data (age)"


def test_donor_age_out_of_range_rejected():
    """An age out of range is rejected."""
    body = client.post(URL, json=_payload(age="40")).json()
    assert body["result"] == "Rejected (Age)"
    assert body["eligibility_result"] == "not_eligible"
    assert body["not_eligibility_reason"] == "age"


def test_donor_borderline_bmi_to_validate():
    """A borderline BMI goes to validation."""
    body = client.post(URL, json=_payload(bmi="28.0")).json()
    assert body["result"] == "To Validate (BMI)"
    assert body["eligibility_result"] == "to_validate"
    assert body["not_eligibility_reason"] == "bmi_to_validate"


def test_donor_other_documents_rejected():
    """Other documents are rejected."""
    body = client.post(URL, json=_payload(document_type="other")).json()
    assert body["result"] == "Rejected (Documentation)"
    assert body["not_eligibility_reason"] == "documentation"
