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
    """A valid candidate is approved."""
    assert classify_donor(valid) == "Approved"


def test_empty_payload_is_inconclusive_on_age():
    """An empty payload is inconclusive on age."""
    assert classify_donor_detailed({}) == ("Inconclusive", "age")


@pytest.mark.parametrize("age", ["20", "32"])
def test_age_limits_are_approved(valid, age):
    """The limit ages are approved."""
    valid["age"] = age
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("age", ["19", "33"])
def test_age_19_and_33_go_to_the_team(valid, age):
    """Ages 19 and 33 go to the team for validation."""
    valid["age"] = age
    assert classify_donor(valid) == "To Validate (Age)"


@pytest.mark.parametrize("age", ["18", "34", "45"])
def test_age_outside_19_to_33_is_rejected(valid, age):
    """An age outside 19 to 33 is rejected."""
    valid["age"] = age
    assert classify_donor(valid) == "Rejected (Age)"


@pytest.mark.parametrize("city", ["Cajicá", "TOCANCIPA", "la calera", "Bogotá"])
def test_allowed_cities_pass(valid, city):
    """Allowed cities pass."""
    valid["city"] = city
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("city", ["Medellín", "Chía", "Otro"])
def test_other_cities_are_rejected(valid, city):
    """Other cities are rejected."""
    valid["city"] = city
    assert classify_donor(valid) == "Rejected (City)"


def test_nationality_is_only_recorded(valid):
    """Nationality is recorded but never rejects."""
    valid["nationality"] = "VEN"
    assert classify_donor(valid) == "Approved"


def test_missing_nationality_is_inconclusive(valid):
    """A missing nationality is inconclusive."""
    del valid["nationality"]
    assert classify_donor_detailed(valid) == ("Inconclusive", "nationality")


@pytest.mark.parametrize("document", ["cedula_ciudadania", "ppt", "PPT"])
def test_cedula_or_ppt_is_approved(valid, document):
    """A cedula or a PPT is approved."""
    valid["document_type"] = document
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("document", ["other", "pasaporte"])
def test_other_documents_are_rejected(valid, document):
    """Other documents are rejected."""
    valid["document_type"] = document
    assert classify_donor(valid) == "Rejected (Documentation)"


def test_missing_document_is_inconclusive(valid):
    """A missing document is inconclusive."""
    del valid["document_type"]
    assert classify_donor_detailed(valid) == ("Inconclusive", "document_type")


@pytest.mark.parametrize("field", ["pregnancies", "abortions", "lactating"])
@pytest.mark.parametrize("answer", ["si", "no"])
def test_informative_answers_never_reject(valid, field, answer):
    """Informative answers never reject."""
    valid[field] = answer
    assert classify_donor(valid) == "Approved"


@pytest.mark.parametrize("field", ["pregnancies", "abortions", "lactating"])
def test_missing_informative_answer_is_inconclusive(valid, field):
    """A missing informative answer is inconclusive."""
    del valid[field]
    assert classify_donor_detailed(valid) == ("Inconclusive", field)


def test_no_sexual_life_is_rejected(valid):
    """No sexual life is rejected."""
    valid["sexual_life"] = "no"
    assert classify_donor(valid) == "Rejected (Sexual Life)"


@pytest.mark.parametrize("height,expected", [("150", "Approved"), ("149", "Rejected (Height)")])
def test_height_limit(valid, height, expected):
    """Height limits decide approval or rejection."""
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
    """BMI ranges decide approval, validation or rejection."""
    valid["bmi"] = bmi
    assert classify_donor(valid) == expected


def test_drug_use_is_rejected(valid):
    """Drug use is rejected."""
    valid["drug_use"] = "si"
    assert classify_donor(valid) == "Rejected (Drug Use)"


def test_no_eps_is_rejected(valid):
    """No active EPS is rejected."""
    valid["eps_active_affiliation"] = "no"
    assert classify_donor(valid) == "Rejected (EPS)"


def test_missing_eps_is_inconclusive(valid):
    """A missing EPS answer is inconclusive."""
    del valid["eps_active_affiliation"]
    assert classify_donor_detailed(valid) == ("Inconclusive", "eps_active_affiliation")


def test_rejection_beats_a_pending_review(valid):
    """A rejection wins over a pending review."""
    valid.update(age="19", drug_use="si")
    assert classify_donor(valid) == "Rejected (Drug Use)"


def test_eligibility_fields():
    """The eligibility fields follow the classification."""
    assert eligibility_fields("Approved") == ("eligible", "none")
    assert eligibility_fields("To Validate (BMI)") == ("to_validate", "bmi_to_validate")
    assert eligibility_fields("Rejected (Documentation)") == ("not_eligible", "documentation")
    assert eligibility_fields("Rejected (Sexual Life)") == ("not_eligible", "sexual_life")
    assert eligibility_fields("Rejected (Drug Use)") == ("not_eligible", "drug_use")
    assert eligibility_fields("Inconclusive", "bmi") == ("incomplete", "missing_data (bmi)")


def test_criteria_are_evaluated_in_order(valid):
    """Criteria are evaluated in order, so the first failure decides."""
    valid.update(age="40", city="Medellin", drug_use="si", document_type="other")
    assert classify_donor(valid) == "Rejected (Age)"
    valid["age"] = "25"
    assert classify_donor(valid) == "Rejected (City)"
    valid["city"] = "Bogota"
    assert classify_donor(valid) == "Rejected (Drug Use)"
    valid["drug_use"] = "no"
    assert classify_donor(valid) == "Rejected (Documentation)"
