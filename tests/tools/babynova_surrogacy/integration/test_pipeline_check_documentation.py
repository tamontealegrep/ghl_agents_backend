"""Prueba el endpoint /check-documentation-sur de punta a punta. Sin dependencias externas."""

from fastapi.testclient import TestClient

from tests.tools.apps import babynova_surrogacy_app as app

client = TestClient(app)


def test_check_documentation_colombian_approved():
    response = client.post("/api/v1/check-documentation-sur", json={"nationality": "COL"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["reason"] == "Colombian nationality"
    assert body["errors"] is None


def test_check_documentation_foreigner_with_ppt_approved():
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "ppt"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["ppt"]


def test_check_documentation_foreigner_with_cedula_ciudadania_approved():
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "cedula_ciudadania"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["cedula_ciudadania"]


def test_check_documentation_foreigner_with_comma_separated_documents_approved():
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "cedula_extranjeria, ppt"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["cedula_extranjeria", "ppt"]


def test_check_documentation_foreigner_with_document_list_approved():
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": ["pasaporte", "cedula_ciudadania"]},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["pasaporte", "cedula_ciudadania"]


def test_check_documentation_foreigner_with_passport_rejected():
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "pasaporte"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is False
    assert "Document not allowed" in body["reason"]


def test_check_documentation_invalid_nationality_format():
    response = client.post("/api/v1/check-documentation-sur", json={"nationality": "XX"})
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is False
    assert "Format error" in body["reason"]


def test_check_documentation_missing_fields_defaults_to_empty():
    response = client.post("/api/v1/check-documentation-sur", json={})
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is False
    assert "Format error" in body["reason"]

