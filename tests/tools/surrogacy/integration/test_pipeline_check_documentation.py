"""Prueba el endpoint /check-documentation-sur de punta a punta. Sin dependencias externas."""

from fastapi.testclient import TestClient

from tests.tools.apps import surrogacy_app as app

client = TestClient(app)


def test_docs_colombian_approved():
    """A Colombian is approved."""
    response = client.post("/api/v1/check-documentation-sur", json={"nationality": "COL"})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["reason"] == "Colombian nationality"
    assert body["errors"] is None


def test_docs_foreigner_ppt_approved():
    """A foreigner with a PPT is approved."""
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "ppt"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["ppt"]


def test_docs_foreigner_cedula_approved():
    """A foreigner with a cedula de ciudadania is approved."""
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "cedula_ciudadania"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["cedula_ciudadania"]


def test_docs_comma_separated_approved():
    """Documents given as a comma-separated string are accepted."""
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "cedula_extranjeria, ppt"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["cedula_extranjeria", "ppt"]


def test_docs_list_approved():
    """Documents given as a list are accepted."""
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": ["pasaporte", "cedula_ciudadania"]},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is True
    assert body["normalized_documents"] == ["pasaporte", "cedula_ciudadania"]


def test_docs_foreigner_passport_rejected():
    """A foreigner with only a passport is rejected."""
    response = client.post(
        "/api/v1/check-documentation-sur",
        json={"nationality": "VEN", "document_type": "pasaporte"},
    )
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is False
    assert "Document not allowed" in body["reason"]


def test_docs_invalid_nationality():
    """An invalid nationality format is rejected."""
    response = client.post("/api/v1/check-documentation-sur", json={"nationality": "XX"})
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is False
    assert "Format error" in body["reason"]


def test_docs_missing_fields():
    """Missing fields are handled as empty values."""
    response = client.post("/api/v1/check-documentation-sur", json={})
    body = response.json()
    assert body["success"] is True
    assert body["approved"] is False
    assert "Format error" in body["reason"]
