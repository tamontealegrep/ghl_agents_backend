"""El endpoint /check-adres de punta a punta, con Croma falso."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from surrogacy.api.v1.endpoints import check_adres as endpoint
from surrogacy.services.croma_client import CromaError

from tests.tools.apps import surrogacy_app as app

client = TestClient(app)
URL = "/api/v1/check-adres"

AFFILIATED = {
    "found": True,
    "full_name": "ANA PEREZ",
    "department": "CUNDINAMARCA",
    "municipality": "SOACHA",
    "affiliations": [
        {
            "entity": "EPS UNO",
            "regime": "CONTRIBUTIVO",
            "status": "ACTIVO",
            "effective_date": "01/01/2020",
            "termination_date": "31/12/2999",
            "affiliate_type": "COTIZANTE",
        }
    ],
}


@pytest.fixture
def croma(monkeypatch):
    calls = []

    async def fake_lookup(body, **kwargs):
        calls.append((body, kwargs))
        return AFFILIATED

    settings = SimpleNamespace(
        croma_api_key="key", croma_base_url="https://croma.test", croma_timeout_seconds=7.0
    )
    monkeypatch.setattr(endpoint, "get_settings", lambda: settings)
    monkeypatch.setattr(endpoint, "lookup_affiliation", fake_lookup)
    return calls, settings


def test_affiliated_person_output(croma):
    """An affiliated person comes back with the documented output."""
    calls, _ = croma

    body = client.post(
        URL, json={"document_type": "cedula_de_ciudadania", "document_number": "1.234.567.890"}
    ).json()

    assert body == {
        "success": True,
        "document_type": "CC",
        "document_number": "1234567890",
        "found": True,
        "full_name": "ANA PEREZ",
        "department": "CUNDINAMARCA",
        "municipality": "SOACHA",
        "has_active_affiliation": True,
        "affiliations": [
            {
                "entity": "EPS UNO",
                "regime": "CONTRIBUTIVO",
                "status": "ACTIVO",
                "effective_date": "01/01/2020",
                "termination_date": "31/12/2999",
                "affiliate_type": "COTIZANTE",
                "active": True,
            }
        ],
        "errors": None,
    }
    sent, kwargs = calls[0]
    assert sent == {"document_type": "CC", "document_number": "1234567890"}
    assert (kwargs["api_key"], kwargs["base_url"], kwargs["timeout_seconds"]) == (
        "key",
        "https://croma.test",
        7.0,
    )


def test_unknown_document_is_not_found(croma, monkeypatch):
    """A document not in the BDUA is a success with found false."""

    async def not_found(body, **kwargs):
        return {"found": False, "full_name": None, "affiliations": []}

    monkeypatch.setattr(endpoint, "lookup_affiliation", not_found)

    body = client.post(URL, json={"document_type": "CC", "document_number": "99999999"}).json()

    assert (body["success"], body["found"], body["has_active_affiliation"], body["affiliations"]) == (
        True,
        False,
        False,
        [],
    )


def test_invalid_input_skips_provider(croma):
    """An invalid input is a normal result and never calls the provider."""
    calls, _ = croma

    body = client.post(URL, json={"document_type": "licencia", "document_number": "123456"}).json()
    assert body["success"] is True and body["found"] is None and "document_type" in body["errors"]

    body = client.post(URL, json={"document_type": "CC"}).json()
    assert body["success"] is True and "document_number" in body["errors"]

    assert calls == []


def test_missing_key_is_failure(croma, monkeypatch):
    """A missing API key is a technical failure."""
    _, settings = croma
    settings.croma_api_key = ""

    body = client.post(URL, json={"document_type": "CC", "document_number": "1234567"}).json()

    assert body["success"] is False and body["errors"] == "Missing CROMA_API_KEY in environment"


def test_provider_failure_is_failure(croma, monkeypatch):
    """A provider failure is a technical failure that keeps its message."""

    async def broken(body, **kwargs):
        raise CromaError("Croma answered HTTP 429: rate limit")

    monkeypatch.setattr(endpoint, "lookup_affiliation", broken)

    body = client.post(URL, json={"document_type": "CC", "document_number": "1234567"}).json()

    assert body["success"] is False and body["found"] is None and "429" in body["errors"]
    assert (body["document_type"], body["document_number"]) == ("CC", "1234567")
