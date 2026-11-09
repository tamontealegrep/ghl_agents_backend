from datetime import date

import pytest

from babynova_surrogacy.services.surrogate_classifier import classify_surrogate


def _date_months_ago(n: int) -> str:
    """Fecha 'YYYY-MM-01' que queda a exactamente n meses del mes actual.

    classify_surrogate compara solo aÃ±o/mes (no dÃ­a) al calcular months_diff,
    asÃ­ que fijar el dÃ­a en 1 hace la prueba determinista sin depender del
    dÃ­a real en que se ejecuta.
    """
    today = date.today()
    total_months = today.year * 12 + (today.month - 1) - n
    year, month = divmod(total_months, 12)
    return date(year, month + 1, 1).isoformat()


@pytest.fixture
def valid_candidate_payload():
    """Payload que satisface las 11 reglas de elegibilidad."""
    return {
        "age": "25",
        "city": "Bogota",
        "eps": "si",
        "number_of_children": "2",
        "last_birth_date": "2023-01-15",
        "number_of_c_sections": "1",
        "abortions": "no",
        "preeclampsia": "no",
        "bmi": "22.5",
        "documentation": "si",
        "drug_use": "no",
    }


# ---------------------------------------------------------------------------
# Caso base
# ---------------------------------------------------------------------------

def test_classify_surrogate_approved_for_valid_candidate(valid_candidate_payload):
    assert classify_surrogate(valid_candidate_payload) == "Approved"


def test_classify_surrogate_inconclusive_when_payload_is_empty():
    assert classify_surrogate({}) == "Inconclusive"


# ---------------------------------------------------------------------------
# Regla 1 â€” Edad
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_age_missing(valid_candidate_payload):
    valid_candidate_payload["age"] = None
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_inconclusive_when_age_not_numeric(valid_candidate_payload):
    valid_candidate_payload["age"] = "veinticinco"
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_timing_when_age_under_18(valid_candidate_payload):
    valid_candidate_payload["age"] = "17"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Timing)"


def test_classify_surrogate_rejected_age_when_age_over_38(valid_candidate_payload):
    valid_candidate_payload["age"] = "39"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Age)"


# ---------------------------------------------------------------------------
# Regla 2 â€” Ciudad
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_city_missing(valid_candidate_payload):
    valid_candidate_payload["city"] = ""
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_city_when_not_allowed(valid_candidate_payload):
    valid_candidate_payload["city"] = "Medellin"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (City)"


def test_classify_surrogate_rejected_city_when_otro(valid_candidate_payload):
    valid_candidate_payload["city"] = "Otro"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (City)"


def test_classify_surrogate_accepts_city_with_accents_and_case(valid_candidate_payload):
    valid_candidate_payload["city"] = "  chÃ­a  "
    assert classify_surrogate(valid_candidate_payload) == "Approved"


# ---------------------------------------------------------------------------
# Regla 3 â€” EPS
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_eps_missing(valid_candidate_payload):
    valid_candidate_payload["eps"] = None
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_eps_when_false(valid_candidate_payload):
    valid_candidate_payload["eps"] = "no"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (EPS)"


# ---------------------------------------------------------------------------
# Regla 4 â€” Numero de Hijos
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_number_of_children_missing(valid_candidate_payload):
    valid_candidate_payload["number_of_children"] = None
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_children_when_no_children(valid_candidate_payload):
    valid_candidate_payload["number_of_children"] = "0"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Children)"


def test_classify_surrogate_rejected_children_when_over_4(valid_candidate_payload):
    valid_candidate_payload["number_of_children"] = "5"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Children)"


# ---------------------------------------------------------------------------
# Regla 5 â€” Fecha del Ultimo Parto
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_last_birth_date_missing(valid_candidate_payload):
    valid_candidate_payload["last_birth_date"] = None
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_inconclusive_when_last_birth_date_unparseable(valid_candidate_payload):
    valid_candidate_payload["last_birth_date"] = "no es una fecha"
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_timing_when_last_birth_within_12_months(valid_candidate_payload):
    valid_candidate_payload["last_birth_date"] = _date_months_ago(3)
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Timing)"


def test_classify_surrogate_accepts_last_birth_over_12_months_ago(valid_candidate_payload):
    valid_candidate_payload["last_birth_date"] = _date_months_ago(13)
    assert classify_surrogate(valid_candidate_payload) == "Approved"


@pytest.mark.parametrize("fmt", ["%Y-%m-%d", "%Y/%m/%d"])
def test_classify_surrogate_last_birth_date_accepts_dash_and_slash_formats(valid_candidate_payload, fmt):
    """El owner pidio explicitamente soportar YYYY-MM-DD y YYYY/MM/DD (2026-08-27)."""
    d = date.today().replace(year=date.today().year - 5)
    valid_candidate_payload["last_birth_date"] = d.strftime(fmt)
    assert classify_surrogate(valid_candidate_payload) == "Approved"


# ---------------------------------------------------------------------------
# Regla 6 â€” Numero de Cesareas
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_number_of_c_sections_missing(valid_candidate_payload):
    valid_candidate_payload["number_of_c_sections"] = None
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_c_sections_when_over_2(valid_candidate_payload):
    valid_candidate_payload["number_of_c_sections"] = "3"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (C-Sections)"


# ---------------------------------------------------------------------------
# Regla 7 â€” Abortos (no rechaza por si solo)
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_abortions_unrecognized(valid_candidate_payload):
    valid_candidate_payload["abortions"] = "tal vez"
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_approved_when_abortions_true_but_rest_ok(valid_candidate_payload):
    valid_candidate_payload["abortions"] = "si"
    assert classify_surrogate(valid_candidate_payload) == "Approved"


# ---------------------------------------------------------------------------
# Reglas booleanas (3, 7, 8, 10, 11) â€” formatos flexibles pedidos por el owner
# (2026-08-27): "si"/"no", "yes"/"no", "true"/"false", insensible a
# mayusculas, y 1/0.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("si", True), ("SI", True), ("Si", True), ("yes", True), ("YES", True),
        ("true", True), ("TRUE", True), ("1", True), (1, True), (True, True),
        ("no", False), ("NO", False), ("No", False), ("false", False), ("FALSE", False),
        ("0", False), (0, False), (False, False),
    ],
)
def test_classify_surrogate_boolean_fields_accept_flexible_values(valid_candidate_payload, raw, expected):
    valid_candidate_payload["preeclampsia"] = raw
    result = classify_surrogate(valid_candidate_payload)
    if expected is True:
        assert result == "Rejected (Preeclampsia)"
    else:
        assert result == "Approved"


# ---------------------------------------------------------------------------
# Regla 8 â€” Preeclampsia
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_preeclampsia_unrecognized(valid_candidate_payload):
    valid_candidate_payload["preeclampsia"] = "tal vez"
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_preeclampsia_when_true(valid_candidate_payload):
    valid_candidate_payload["preeclampsia"] = "si"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Preeclampsia)"


# ---------------------------------------------------------------------------
# Regla 9 â€” IMC
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_bmi_missing(valid_candidate_payload):
    valid_candidate_payload["bmi"] = None
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


@pytest.mark.parametrize("bmi", ["18.4", "30.0"])
def test_classify_surrogate_rejected_bmi_when_out_of_range(valid_candidate_payload, bmi):
    valid_candidate_payload["bmi"] = bmi
    assert classify_surrogate(valid_candidate_payload) == "Rejected (BMI)"


@pytest.mark.parametrize("bmi", ["18.5", "29.9"])
def test_classify_surrogate_accepts_bmi_at_range_boundaries(valid_candidate_payload, bmi):
    valid_candidate_payload["bmi"] = bmi
    assert classify_surrogate(valid_candidate_payload) == "Approved"


# ---------------------------------------------------------------------------
# Regla 10 â€” Documentos
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_documentation_unrecognized(valid_candidate_payload):
    valid_candidate_payload["documentation"] = "tal vez"
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_documentation_when_false(valid_candidate_payload):
    valid_candidate_payload["documentation"] = "no"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Documentation)"


# ---------------------------------------------------------------------------
# Regla 11 â€” Drogas
# ---------------------------------------------------------------------------

def test_classify_surrogate_inconclusive_when_drug_use_unrecognized(valid_candidate_payload):
    valid_candidate_payload["drug_use"] = "tal vez"
    assert classify_surrogate(valid_candidate_payload) == "Inconclusive"


def test_classify_surrogate_rejected_drug_use_when_true(valid_candidate_payload):
    valid_candidate_payload["drug_use"] = "si"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Drug Use)"


# ---------------------------------------------------------------------------
# Orden de evaluacion â€” la primera regla que falla determina el resultado
# ---------------------------------------------------------------------------

def test_classify_surrogate_stops_at_first_failing_rule(valid_candidate_payload):
    """Edad invalida (regla 1) debe ganar aunque tambien falle ciudad (regla 2)."""
    valid_candidate_payload["age"] = "45"
    valid_candidate_payload["city"] = "Medellin"
    assert classify_surrogate(valid_candidate_payload) == "Rejected (Age)"


def test_eligibility_fields_map_each_classification_label():
    from babynova_surrogacy.services.surrogate_classifier import eligibility_fields

    assert eligibility_fields("Approved") == ("approved", "none")
    assert eligibility_fields("Inconclusive") == ("inconclusive", "missing_data")
    assert eligibility_fields("Rejected (Age)") == ("rejected", "age")
    assert eligibility_fields("Rejected (Timing)") == ("rejected", "timing")
    assert eligibility_fields("Rejected (C-Sections)") == ("rejected", "c_sections")
    assert eligibility_fields("Rejected (Drug Use)") == ("rejected", "drug_use")
