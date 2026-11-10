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
        "drug_use": "no",
        "availability": "si",
    }


def classify(data):
    return classify_surrogate(data, today=TODAY)


def test_valid_candidate_is_approved(valid):
    assert classify(valid) == "Approved"


def test_empty_payload_is_inconclusive():
    assert classify({}) == "Inconclusive"


@pytest.mark.parametrize("age", ["17", "39", "45"])
def test_age_outside_18_to_38_is_rejected_as_age(valid, age):
    valid["age"] = age
    assert classify(valid) == "Rejected (Age)"


@pytest.mark.parametrize("age", ["18", "38"])
def test_age_limits_are_accepted(valid, age):
    valid["age"] = age
    assert classify(valid) == "Approved"


def test_city_outside_the_list_is_rejected(valid):
    valid["city"] = "Medellin"
    assert classify(valid) == "Rejected (City)"


@pytest.mark.parametrize("children", ["0", "5"])
def test_children_out_of_range_is_rejected(valid, children):
    valid["number_of_children"] = children
    assert classify(valid) == "Rejected (Children)"


# --- 4.1 Tiempo desde el ultimo parto -------------------------------------

def test_c_section_less_than_18_months_ago_is_rejected(valid):
    valid["last_birth_date"] = _months_ago(17)
    valid["birth_type"] = "csection"
    assert classify(valid) == "Rejected (Timing)"


def test_c_section_exactly_18_months_ago_is_accepted(valid):
    valid["last_birth_date"] = _months_ago(18)
    valid["birth_type"] = "csection"
    assert classify(valid) == "Approved"


def test_natural_birth_less_than_12_months_ago_is_rejected(valid):
    valid["last_birth_date"] = _months_ago(11)
    valid["birth_type"] = "natural"
    assert classify(valid) == "Rejected (Timing)"


def test_natural_birth_between_12_and_18_months_ago_is_accepted(valid):
    valid["last_birth_date"] = _months_ago(14)
    valid["birth_type"] = "parto natural"
    assert classify(valid) == "Approved"


def test_recent_birth_without_type_is_inconclusive(valid):
    valid["last_birth_date"] = _months_ago(10)
    assert classify(valid) == "Inconclusive"


def test_birth_type_is_not_needed_after_18_months(valid):
    valid["last_birth_date"] = _months_ago(30)
    valid.pop("birth_type", None)
    assert classify(valid) == "Approved"


def test_missing_last_birth_date_is_inconclusive(valid):
    valid["last_birth_date"] = ""
    assert classify(valid) == "Inconclusive"


# --- 4.2 Cesareas ----------------------------------------------------------

@pytest.mark.parametrize("count,expected", [("0", "Approved"), ("2", "Approved"), ("3", "Rejected (C-Sections)")])
def test_c_section_count(valid, count, expected):
    valid["number_of_c_sections"] = count
    assert classify(valid) == expected


# --- 4.3 Abortos -----------------------------------------------------------

def test_abortion_history_does_not_reject(valid):
    valid["abortions"] = "si"
    assert classify(valid) == "Approved"


def test_unknown_abortion_answer_is_inconclusive(valid):
    valid["abortions"] = "unknown"
    assert classify(valid) == "Inconclusive"


# --- 4.4 Preeclampsia ------------------------------------------------------

def test_preeclampsia_history_is_rejected(valid):
    valid["preeclampsia"] = "si"
    assert classify(valid) == "Rejected (Preeclampsia)"


# --- Resto de criterios ----------------------------------------------------

@pytest.mark.parametrize("bmi", ["18.4", "30"])
def test_bmi_out_of_range_is_rejected(valid, bmi):
    valid["bmi"] = bmi
    assert classify(valid) == "Rejected (BMI)"


@pytest.mark.parametrize("document", ["cedula_ciudadania", "ppt", "PPT", "Cedula Ciudadania"])
def test_cc_and_ppt_are_accepted(valid, document):
    valid["document_type"] = document
    assert classify(valid) == "Approved"


@pytest.mark.parametrize("document", ["other", "pasaporte", "cedula_extranjeria"])
def test_other_documents_are_rejected(valid, document):
    valid["document_type"] = document
    assert classify(valid) == "Rejected (Documentation)"


def test_drug_use_is_rejected(valid):
    valid["drug_use"] = "si"
    assert classify(valid) == "Rejected (Drug Use)"


def test_no_time_availability_is_rejected(valid):
    valid["availability"] = "no"
    assert classify(valid) == "Rejected (Availability)"


def test_missing_availability_is_inconclusive(valid):
    valid["availability"] = None
    assert classify(valid) == "Inconclusive"


def test_nationality_is_recorded_but_never_rejects(valid):
    valid["nationality"] = "VEN"
    assert classify(valid) == "Approved"


def test_missing_field_is_reported(valid):
    from surrogacy.services.surrogate_classifier import classify_surrogate_detailed

    valid.pop("last_birth_date", None)
    assert classify_surrogate_detailed(valid, TODAY) == ("Inconclusive", "last_birth_date")


def test_missing_birth_type_is_reported_only_for_recent_births(valid):
    from surrogacy.services.surrogate_classifier import classify_surrogate_detailed

    valid["last_birth_date"] = "2025-06-01"
    valid.pop("birth_type", None)
    assert classify_surrogate_detailed(valid, TODAY) == ("Inconclusive", "birth_type")


def test_eligibility_reason_names_the_missing_field():
    assert eligibility_fields("Inconclusive", "last_birth_date") == ("inconclusive", "missing_data (last_birth_date)")


def test_eps_is_ignored(valid):
    valid["eps"] = "no"
    assert classify(valid) == "Approved"


@pytest.mark.parametrize(
    "result,expected",
    [
        ("Approved", ("approved", "none")),
        ("Inconclusive", ("inconclusive", "missing_data")),
        ("Rejected (Age)", ("rejected", "age")),
        ("Rejected (Timing)", ("rejected", "timing")),
        ("Rejected (Availability)", ("rejected", "availability")),
        ("Rejected (Documentation)", ("rejected", "documentation")),
    ],
)
def test_eligibility_fields(result, expected):
    assert eligibility_fields(result) == expected
