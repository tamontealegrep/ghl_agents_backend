from fastapi.testclient import TestClient

from tests.tools.apps import babynova_surrogacy_app as app

client = TestClient(app)


def test_surrogate_classification_endpoint_returns_approved_for_valid_payload():
    payload = {
        "age": "25", "city": "Bogota", "number_of_children": "2",
        "last_birth_date": "2020-01-15", "number_of_c_sections": "1",
        "abortions": "no", "preeclampsia": "no", "bmi": "22.5",
        "documentation": "si", "drug_use": "no",
    }
    response = client.post("/api/v1/surrogate-classification", json=payload)
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "result": "Approved",
        "eligibility_result": "approved",
        "eligibility_reason": "none",
        "errors": None,
    }


def test_surrogate_classification_endpoint_returns_inconclusive_for_empty_payload():
    response = client.post("/api/v1/surrogate-classification", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["result"] == "Inconclusive"
    assert body["errors"] is None


def test_surrogate_classification_endpoint_rejects_out_of_range_age():
    response = client.post("/api/v1/surrogate-classification", json={"age": "45"})
    assert response.json()["result"] == "Rejected (Age)"


def test_surrogate_classification_endpoint_ignores_extra_unknown_fields():
    response = client.post(
        "/api/v1/surrogate-classification",
        json={"age": "45", "campo_no_declarado_por_ghl": "algo"},
    )
    assert response.status_code == 200
    assert response.json()["result"] == "Rejected (Age)"

