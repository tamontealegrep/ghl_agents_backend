import pytest

from agent_backend.builtin_tools.services.bmi_calculator import calculate_bmi


def test_calculates_and_rounds_to_one_decimal():
    result = calculate_bmi(70, 175)
    assert result == {"bmi": 22.9, "errors": None}


def test_accepts_string_numbers():
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
        ("no-es-un-numero", 175),
        (70, "no-es-un-numero"),
    ],
)
def test_invalid_inputs_return_null_bmi_with_error(weight_kg, height_cm):
    result = calculate_bmi(weight_kg, height_cm)
    assert result == {"bmi": None, "errors": "Valores invalidos: peso y altura deben ser mayores que 0"}


def test_rounds_half_up_not_banker_rounding():
    # height_cm=100 -> height_m=1 -> bmi == weight_kg exactamente (22.25,
    # representable de forma exacta en binario). Math.round de JS redondea
    # .5 siempre hacia arriba -> 22.3; el round() nativo de Python usaria
    # "banker's rounding" y daria 22.2 -- se replica el comportamiento de JS.
    result = calculate_bmi(22.25, 100)
    assert result["bmi"] == 22.3
