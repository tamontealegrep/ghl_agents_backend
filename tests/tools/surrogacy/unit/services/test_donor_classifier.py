import pytest
from surrogacy.services.donor_classifier import classify_donor, classify_donor_detailed, eligibility_fields


@pytest.fixture
def valid():
    return {
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


def test_valid_candidate_is_approved(valid):
    assert classify_donor(valid) == "Approved"


def test_empty_payload_is_inconclusive_on_age():
    assert classify_donor_detailed({}) == ("Inconclusive", "age")


@pytest.mark.parametrize("age", ["20", "32"])
def test_age_limits_are_approved(valid, age):
    valid["age"] = age
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("age", ["19", "33"])
def test_age_19_and_33_go_to_the_team(valid, age):
    valid["age"] = age
    assert classify_donor(valid) == "To Validate (Age)"


@pytest.mark.parametrize("age", ["18", "34", "45"])
def test_age_outside_19_to_33_is_rejected(valid, age):
    valid["age"] = age
    assert classify_donor(valid) == "Rejected (Age)"


@pytest.mark.parametrize("city", ["Cajicá", "TOCANCIPA", "la calera", "Bogotá"])
def test_allowed_cities_pass(valid, city):
    valid["city"] = city
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("city", ["Medellín", "Chía", "Otro"])
def test_other_cities_are_rejected(valid, city):
    valid["city"] = city
    assert classify_donor(valid) == "Rejected (City)"


def test_nationality_is_only_recorded(valid):
    valid["nationality"] = "VEN"
    assert classify_donor(valid) == "Approved"


def test_missing_nationality_is_inconclusive(valid):
    del valid["nationality"]
    assert classify_donor_detailed(valid) == ("Inconclusive", "nationality")


@pytest.mark.parametrize("document", ["cedula_ciudadania", "ppt", "PPT"])
def test_cedula_or_ppt_is_approved(valid, document):
    valid["document_type"] = document
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("document", ["other", "pasaporte"])
def test_other_documents_are_rejected(valid, document):
    valid["document_type"] = document
    assert classify_donor(valid) == "Rejected (Documentation)"


def test_missing_document_is_inconclusive(valid):
    del valid["document_type"]
    assert classify_donor_detailed(valid) == ("Inconclusive", "document_type")


@pytest.mark.parametrize("field", ["pregnancies", "abortions", "lactating"])
@pytest.mark.parametrize("answer", ["si", "no"])
def test_informative_answers_never_reject(valid, field, answer):
    valid[field] = answer
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("field", ["pregnancies", "abortions", "lactating"])
def test_missing_informative_answer_is_inconclusive(valid, field):
    del valid[field]
    assert classify_donor_detailed(valid) == ("Inconclusive", field)


def test_no_sexual_life_is_rejected(valid):
    valid["sexual_life"] = "no"
    assert classify_donor(valid) == "Rejected (Sexual Life)"


@pytest.mark.parametrize("height,expected", [("150", "Approved"), ("149", "Rejected (Height)")])
def test_height_limit(valid, height, expected):
    valid["height_cm"] = height
    assert classify_donor(valid) == expected


@pytest.mark.parametrize(
    "bmi,expected",
    [
        ("17.9", "Approved"),
        ("27.9", "Approved"),
        ("17.5", "To Validate (BMI)"),
        ("28.0", "To Validate (BMI)"),
        ("16.9", "Rejected (BMI)"),
        ("28.1", "Rejected (BMI)"),
    ],
)
def test_bmi_ranges(valid, bmi, expected):
    valid["bmi"] = bmi
    assert classify_donor(valid) == expected


def test_drug_use_is_rejected(valid):
    valid["drug_use"] = "si"
    assert classify_donor(valid) == "Rejected (Drug Use)"


def test_no_eps_is_rejected(valid):
    valid["eps_active_affiliation"] = "no"
    assert classify_donor(valid) == "Rejected (EPS)"


def test_missing_eps_is_inconclusive(valid):
    del valid["eps_active_affiliation"]
    assert classify_donor_detailed(valid) == ("Inconclusive", "eps_active_affiliation")


def test_rejection_beats_a_pending_review(valid):
    valid.update(age="19", drug_use="si")
    assert classify_donor(valid) == "Rejected (Drug Use)"


def test_eligibility_fields():
    assert eligibility_fields("Approved") == ("eligible", "none")
    assert eligibility_fields("To Validate (BMI)") == ("to_validate", "bmi_to_validate")
    assert eligibility_fields("Rejected (Documentation)") == ("not_eligible", "documentation")
    assert eligibility_fields("Rejected (Sexual Life)") == ("not_eligible", "sexual_life")
    assert eligibility_fields("Rejected (Drug Use)") == ("not_eligible", "drug_use")
    assert eligibility_fields("Inconclusive", "bmi") == ("incomplete", "missing_data (bmi)")


def test_criteria_are_evaluated_in_order(valid):
    valid.update(age="40", city="Medellin", drug_use="si", document_type="other")
    assert classify_donor(valid) == "Rejected (Age)"
    valid["age"] = "25"
    assert classify_donor(valid) == "Rejected (City)"
    valid["city"] = "Bogota"
    assert classify_donor(valid) == "Rejected (Drug Use)"
    valid["drug_use"] = "no"
    assert classify_donor(valid) == "Rejected (Documentation)"
