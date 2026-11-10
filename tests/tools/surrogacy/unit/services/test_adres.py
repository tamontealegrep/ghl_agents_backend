"""Regla de negocio y cliente de la consulta ADRES (Croma). Sin red: el transporte HTTP es falso."""

import asyncio

import httpx
import pytest
from surrogacy.services.adres import (
    DOCUMENT_TYPES,
    build_result,
    normalize_document_number,
    normalize_document_type,
    prepare_lookup,
)
from surrogacy.services.croma_client import CromaError, lookup_affiliation


@pytest.mark.parametrize("code", DOCUMENT_TYPES)
def test_every_abbreviation_is_accepted_in_either_case(code):
    assert normalize_document_type(code) == code
    assert normalize_document_type(code.lower()) == code


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("cedula_de_ciudadania", "CC"),
        ("tarjeta_de_identidad", "TI"),
        ("cedula_de_extranjeria", "CE"),
        ("registro_civil", "RC"),
        ("pasaporte", "PA"),
        ("permiso_especial_de_permanencia", "PEP"),
        ("permiso_por_proteccion_temporal", "PPT"),
        ("Cédula de Ciudadanía", "CC"),  # accents, capitals and spaces
        ("cedula_ciudadania", "CC"),  # the names this plugin's other tools already use
        ("cedula_extranjeria", "CE"),
        ("  ppt ", "PPT"),
    ],
)
def test_long_names_and_loose_spellings_map_to_the_abbreviation(raw, expected):
    assert normalize_document_type(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "otro", "licencia", "XX"])
def test_unknown_document_types_are_not_guessed(raw):
    assert normalize_document_type(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234567890", "1234567890"),
        ("1.234.567.890", "1234567890"),
        (" 123 456 ", "123456"),
        (1234567890, "1234567890"),
    ],
)
def test_document_numbers_lose_separators(raw, expected):
    assert normalize_document_number(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "12", "x" * 31])
def test_document_numbers_outside_3_to_30_characters_are_refused(raw):
    assert normalize_document_number(raw) is None


def test_a_valid_input_builds_the_providers_body():
    assert prepare_lookup("cc", "1.234.567.890") == (
        {"document_type": "CC", "document_number": "1234567890"},
        None,
    )


def test_an_invalid_input_explains_what_is_wrong_without_raising():
    body, error = prepare_lookup("licencia", "123456")
    assert body is None and "document_type" in error and "PPT" in error
    body, error = prepare_lookup("CC", "1")
    assert body is None and "document_number" in error


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
        },
        {
            "entity": "EPS DOS",
            "regime": "SUBSIDIADO",
            "status": "RETIRADO",
            "effective_date": "01/01/2015",
            "termination_date": "31/12/2019",
            "affiliate_type": "BENEFICIARIO",
        },
    ],
}


def test_an_affiliation_is_active_only_when_it_has_no_termination_date():
    result = build_result(AFFILIATED)
    assert [a["active"] for a in result["affiliations"]] == [True, False]
    assert result["has_active_affiliation"] is True
    assert (result["found"], result["full_name"], result["municipality"]) == (True, "ANA PEREZ", "SOACHA")


def test_nobody_active_means_no_active_affiliation():
    data = {**AFFILIATED, "affiliations": AFFILIATED["affiliations"][1:]}
    assert build_result(data)["has_active_affiliation"] is False


def test_a_document_not_in_the_bdua_is_a_normal_result():
    result = build_result({"found": False, "full_name": None, "affiliations": []})
    assert result == {
        "found": False,
        "full_name": None,
        "department": None,
        "municipality": None,
        "affiliations": [],
        "has_active_affiliation": False,
    }
    assert build_result(None)["found"] is False


# ------------------------------------------------------------------ the HTTP client
BODY = {"document_type": "CC", "document_number": "1234567890"}


def _call(handler):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await lookup_affiliation(
                BODY, api_key="key123", base_url="https://api.croma.run/", timeout_seconds=5, client=client
            )

    return asyncio.run(run())


def test_the_request_goes_to_the_affiliation_endpoint_with_the_bearer_key():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=request.content)
        return httpx.Response(200, json={"data": AFFILIATED})

    data = _call(handler)

    assert seen["url"] == "https://api.croma.run/co/adres/affiliation-status/v1"
    assert seen["auth"] == "Bearer key123"
    assert b'"document_type":"CC"' in seen["body"].replace(b" ", b"")
    assert data["full_name"] == "ANA PEREZ"


def test_a_body_without_the_data_wrapper_is_still_read():
    assert _call(lambda request: httpx.Response(200, json=AFFILIATED))["found"] is True


def test_provider_errors_are_reported_with_their_message():
    def handler(request):
        return httpx.Response(
            401, json={"error": {"type": "auth", "code": "invalid_key", "message": "Bad key"}}
        )

    with pytest.raises(CromaError, match="HTTP 401: Bad key"):
        _call(handler)


def test_an_error_without_a_json_body_still_names_the_status():
    with pytest.raises(CromaError, match="HTTP 503"):
        _call(lambda request: httpx.Response(503, text="down"))


def test_a_lookup_that_became_a_job_is_reported_not_polled():
    with pytest.raises(CromaError, match="did not finish"):
        _call(lambda request: httpx.Response(202, json={"data": {"job": "abc"}}))


def test_timeouts_and_network_failures_become_croma_errors():
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def refused(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(CromaError, match="within 5 seconds"):
        _call(timeout)
    with pytest.raises(CromaError, match="Could not reach Croma"):
        _call(refused)
