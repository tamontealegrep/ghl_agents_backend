import pytest

from agent_backend.builtin_tools.services.bmi_calculator import calculate_bmi


def test_bmi_is_rounded_to_one_decimal():
    """70 kg at 175 cm gives 22.9, returned under both `bmi` and `imc`."""
    assert calculate_bmi(70, 175) == {"bmi": 22.9, "imc": 22.9, "errors": None}


def test_bmi_accepts_numeric_strings():
    """Weight and height given as strings are parsed as numbers."""
    result = calculate_bmi("70", "175")
    assert result["bmi"] == 22.9
    assert result["errors"] is None


@pytest.mark.parametrize(
    "weight_kg,height_cm",
    [
        (0, 175),
        (70, 0),
        (-70, 175),
        (70, -175),
        (None, 175),
        (70, None),
        ("not-a-number", 175),
        (70, "not-a-number"),
    ],
)
def test_bmi_invalid_input_returns_error(weight_kg, height_cm):
    """Zero, negative, missing or non-numeric values give a null BMI and an error message."""
    result = calculate_bmi(weight_kg, height_cm)
    assert result == {
        "bmi": None,
        "imc": None,
        "errors": "Valores invalidos: peso y altura deben ser mayores que 0",
    }


def test_bmi_rounds_half_up():
    """22.25 rounds to 22.3 (like the original JS Math.round), not to 22.2 as Python's banker's rounding would."""
    assert calculate_bmi(22.25, 100)["bmi"] == 22.3
