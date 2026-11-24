import pytest
from desk.services.visa_checker import VisaCheckerService


@pytest.fixture
def visa_service():
    return VisaCheckerService()


def test_visa_no_requirement(visa_service):
    # España no requiere visa
    """A country with no visa requirement is reported as such."""
    response = visa_service.check_visas("Spain")
    assert response.success is True
    assert response.nationality == "Spain"
    assert response.requires_visa is False
    assert response.conditional_visa is False
    assert response.errors is None


def test_visa_colombia(visa_service):
    # Colombia no requiere visa
    """Colombia is answered correctly."""
    response = visa_service.check_visas("Colombia")
    assert response.success is True
    assert response.requires_visa is False
    assert response.conditional_visa is False


def test_visa_required(visa_service):
    # Afganistán requiere visa
    """A country that requires a visa is reported as such."""
    response = visa_service.check_visas("Afghanistan")
    assert response.success is True
    assert response.requires_visa is True
    assert response.conditional_visa is False


def test_visa_conditional(visa_service):
    # China es condicional
    """A conditional requirement is reported as such."""
    response = visa_service.check_visas("China")
    assert response.success is True
    assert response.requires_visa is True
    assert response.conditional_visa is True


def test_visa_multiple_mixed(visa_service):
    # Múltiples nacionalidades: Spain (No) + China (Cond) + AFG (Req)
    # Como España no requiere visa, el resultado global debería ser False
    """Several countries with mixed requirements are all answered."""
    response = visa_service.check_visas(["Spain", "China", "AFG"])
    assert response.success is True
    assert response.requires_visa is False
    assert response.conditional_visa is False
    assert "Spain: No requiere visa" in response.summary


def test_visa_comma_separated(visa_service):
    """A comma-separated list of countries is split and answered."""
    response = visa_service.check_visas("Spain, China")
    assert response.success is True
    assert "Spain" in response.nationality
    assert "China" in response.nationality


def test_visa_iso_codes(visa_service):
    # DEU (Alemania) - No visa
    """ISO country codes are accepted."""
    response = visa_service.check_visas("DEU")
    assert response.success is True
    assert response.requires_visa is False

    # CHN (China) - Conditional
    response = visa_service.check_visas("CHN")
    assert response.success is True
    assert response.requires_visa is True
    assert response.conditional_visa is True


def test_visa_input_normalised(visa_service):
    # España con acento, espacios y minúsculas
    """Odd casing, accents and blanks in the input are normalised."""
    response = visa_service.check_visas("  españa  ")
    assert response.success is True
    assert response.nationality == "españa"
    assert response.requires_visa is False

    # Saudi Arabia con doble espacio
    response = visa_service.check_visas("SAUDI  ARABIA")
    assert response.success is True
    assert response.nationality == "SAUDI ARABIA"
    assert response.requires_visa is True

    # ALEMANIA con espacios locos
    response = visa_service.check_visas("  Alemania  ,   CHINA  ")
    assert response.success is True
    assert response.nationality == "Alemania, CHINA"
    assert response.requires_visa is False  # Porque Alemania no requiere
