from datetime import date

import pytest
from surrogacy.services.surrogate_classifier import (
    classify_surrogate,
    eligibility_fields,
)

TODAY = date(2026, 11, 15)


def _months_ago(n: int) -> str:
    """Fecha 'YYYY-MM-01' a exactamente n meses del mes de TODAY (la regla solo compara anio y mes)."""
    total = TODAY.year * 12 + (TODAY.month - 1) - n
    year, month = divmod(total, 12)
    return date(year, month + 1, 1).isoformat()


@pytest.fixture
def valid():
    return {
        "age": "28",
        "city": "Bogota",
        "nationality": "COL",
        "number_of_children": "2",
        "last_birth_date": _months_ago(40),
        "number_of_c_sections": "1",
        "abortions": "no",
        "preeclampsia": "no",
        "bmi": "22.5",
        "document_type": "cedula_ciudadania",
        "eps_active_affiliation": "yes",
        "drug_use": "no",
        "availability": "si",
    }


def classify(data):
    return classify_surrogate(data, today=TODAY)


def test_valid_candidate_is_approved(valid):
    """A valid candidate is approved."""
    assert classify(valid) == "Approved"


def test_empty_payload_is_inconclusive():
    """An empty payload is inconclusive."""
    assert classify({}) == "Inconclusive"


@pytest.mark.parametrize("age", ["17", "39", "45"])
def test_age_outside_18_to_38_rejected(valid, age):
    """An age outside 18 to 38 is rejected."""
    valid["age"] = age
    assert classify(valid) == "Rejected (Age)"


@pytest.mark.parametrize("age", ["18", "38"])
def test_age_limits_are_accepted(valid, age):
    """The limit ages are accepted."""
    valid["age"] = age
    assert classify(valid) == "Approved"


def test_city_outside_the_list_is_rejected(valid):
    """A city outside the list is rejected."""
    valid["city"] = "Medellin"
    assert classify(valid) == "Rejected (City)"


@pytest.mark.parametrize("children", ["0", "5"])
def test_children_out_of_range_is_rejected(valid, children):
    """A number of children out of range is rejected."""
    valid["number_of_children"] = children
    assert classify(valid) == "Rejected (Children)"


# --- 4.1 Tiempo desde el ultimo parto -------------------------------------


def test_recent_c_section_rejected(valid):
    """A C-section less than 18 months ago is rejected."""
    valid["last_birth_date"] = _months_ago(17)
    valid["birth_type"] = "csection"
    assert classify(valid) == "Rejected (Timing)"


def test_c_section_18_months_accepted(valid):
    """A C-section exactly 18 months ago is accepted."""
    valid["last_birth_date"] = _months_ago(18)
    valid["birth_type"] = "csection"
    assert classify(valid) == "Approved"


def test_recent_natural_birth_rejected(valid):
    """A natural birth less than 12 months ago is rejected."""
    valid["last_birth_date"] = _months_ago(11)
    valid["birth_type"] = "natural"
    assert classify(valid) == "Rejected (Timing)"


def test_natural_birth_12_to_18_accepted(valid):
    """A natural birth 12 to 18 months ago is accepted."""
    valid["last_birth_date"] = _months_ago(14)
    valid["birth_type"] = "parto natural"
    assert classify(valid) == "Approved"


def test_recent_birth_without_type_is_inconclusive(valid):
    """A recent birth without its type is inconclusive."""
    valid["last_birth_date"] = _months_ago(10)
    assert classify(valid) == "Inconclusive"


def test_birth_type_is_not_needed_after_18_months(valid):
    """The birth type is not needed after 18 months."""
    valid["last_birth_date"] = _months_ago(30)
    valid.pop("birth_type", None)
    assert classify(valid) == "Approved"


def test_missing_last_birth_date_is_inconclusive(valid):
    """A missing last birth date is inconclusive."""
    valid["last_birth_date"] = ""
    assert classify(valid) == "Inconclusive"


# --- 4.2 Cesareas ----------------------------------------------------------


@pytest.mark.parametrize(
    "count,expected", [("0", "Approved"), ("2", "Approved"), ("3", "Rejected (C-Sections)")]
)
def test_c_section_count(valid, count, expected):
    """The number of C-sections decides approval or rejection."""
    valid["number_of_c_sections"] = count
    assert classify(valid) == expected


# --- 4.3 Abortos -----------------------------------------------------------


def test_abortion_history_does_not_reject(valid):
    """A history of abortions does not reject."""
    valid["abortions"] = "si"
    assert classify(valid) == "Approved"


def test_unknown_abortion_answer_is_inconclusive(valid):
    """An unknown abortion answer is inconclusive."""
    valid["abortions"] = "unknown"
    assert classify(valid) == "Inconclusive"


# --- 4.4 Preeclampsia ------------------------------------------------------


def test_preeclampsia_history_is_rejected(valid):
    """A history of preeclampsia is rejected."""
    valid["preeclampsia"] = "si"
    assert classify(valid) == "Rejected (Preeclampsia)"


# --- Resto de criterios ----------------------------------------------------


@pytest.mark.parametrize("bmi", ["18.4", "30"])
def test_bmi_out_of_range_is_rejected(valid, bmi):
    """A BMI out of range is rejected."""
    valid["bmi"] = bmi
    assert classify(valid) == "Rejected (BMI)"


@pytest.mark.parametrize("document", ["cedula_ciudadania", "ppt", "PPT", "Cedula Ciudadania"])
def test_cc_and_ppt_are_accepted(valid, document):
    """A cedula or a PPT is accepted."""
    valid["document_type"] = document
    assert classify(valid) == "Approved"


@pytest.mark.parametrize("document", ["other", "pasaporte", "cedula_extranjeria"])
def test_other_documents_are_rejected(valid, document):
    """Other documents are rejected."""
    valid["document_type"] = document
    assert classify(valid) == "Rejected (Documentation)"


def test_drug_use_is_rejected(valid):
    """Drug use is rejected."""
    valid["drug_use"] = "si"
    assert classify(valid) == "Rejected (Drug Use)"


def test_no_time_availability_is_rejected(valid):
    """No time availability is rejected."""
    valid["availability"] = "no"
    assert classify(valid) == "Rejected (Availability)"


def test_missing_availability_is_inconclusive(valid):
    """A missing availability answer is inconclusive."""
    valid["availability"] = None
    assert classify(valid) == "Inconclusive"


def test_nationality_never_rejects(valid):
    """Nationality is recorded but never rejects."""
    valid["nationality"] = "VEN"
    assert classify(valid) == "Approved"


def test_missing_field_is_reported(valid):
    """The missing field is reported with an inconclusive result."""
    from surrogacy.services.surrogate_classifier import classify_surrogate_detailed

    valid.pop("last_birth_date", None)
    assert classify_surrogate_detailed(valid, TODAY) == ("Inconclusive", "last_birth_date")


def test_birth_type_reported_only_if_recent(valid):
    """A missing birth type is reported only for recent births."""
    from surrogacy.services.surrogate_classifier import classify_surrogate_detailed

    valid["last_birth_date"] = "2025-06-01"
    valid.pop("birth_type", None)
    assert classify_surrogate_detailed(valid, TODAY) == ("Inconclusive", "birth_type")


def test_reason_names_missing_field():
    """The not-eligible reason names the missing field."""
    assert eligibility_fields("Inconclusive", "last_birth_date") == (
        "inconclusive",
        "missing_data (last_birth_date)",
    )


@pytest.mark.parametrize("value", ["no", "NO", "false", False])
def test_no_active_eps_rejected(valid, value):
    """No active EPS affiliation is rejected."""
    valid["eps_active_affiliation"] = value
    assert classify(valid) == "Rejected (EPS)"


@pytest.mark.parametrize("value", ["yes", "si", "true", True])
def test_active_eps_accepted(valid, value):
    """An active EPS affiliation is accepted."""
    valid["eps_active_affiliation"] = value
    assert classify(valid) == "Approved"


@pytest.mark.parametrize("value", [None, "", "unknown"])
def test_missing_eps_inconclusive(valid, value):
    """A missing EPS answer is inconclusive."""
    from surrogacy.services.surrogate_classifier import classify_surrogate_detailed

    valid["eps_active_affiliation"] = value
    assert classify_surrogate_detailed(valid, TODAY) == ("Inconclusive", "eps_active_affiliation")


@pytest.mark.parametrize(
    "result,expected",
    [
        ("Approved", ("approved", "none")),
        ("Inconclusive", ("inconclusive", "missing_data")),
        ("Rejected (Age)", ("rejected", "age")),
        ("Rejected (Timing)", ("rejected", "timing")),
        ("Rejected (Availability)", ("rejected", "availability")),
        ("Rejected (Documentation)", ("rejected", "documentation")),
        ("Rejected (EPS)", ("rejected", "eps")),
    ],
)
def test_eligibility_fields(result, expected):
    """The eligibility fields follow the classification."""
    assert eligibility_fields(result) == expected


def test_missing_document_type_inconclusive(valid):
    """A missing document type is inconclusive."""
    from surrogacy.services.surrogate_classifier import classify_surrogate_detailed

    valid["document_type"] = ""
    assert classify_surrogate_detailed(valid, TODAY) == ("Inconclusive", "document_type")


def test_document_is_checked_last(valid):
    """The document is checked last, so earlier failures win."""
    valid["document_type"] = "pasaporte"
    valid["drug_use"] = "si"
    assert classify(valid) == "Rejected (Drug Use)"
