"""
Module.

    Reglas de negocio puras de cálculo de BMI (índice de masa corporal). No sabe
    nada de HTTP. Port 1:1 del código JS del nodo "Calcular IMC" del flujo de GHL
    "calcular_imc".
"""

import math
from typing import Any


def _parse_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return None


def calculate_bmi(raw_weight_kg: Any, raw_height_cm: Any) -> dict[str, Any]:
    """Calcula el BMI a partir de peso (kg) y altura (cm).

    Devuelve {bmi, errors}.
    """
    weight_kg = _parse_float(raw_weight_kg)
    height_cm = _parse_float(raw_height_cm)

    if not weight_kg or not height_cm or height_cm <= 0 or weight_kg <= 0:
        return {"bmi": None, "imc": None, "errors": "Valores invalidos: peso y altura deben ser mayores que 0"}

    height_m = height_cm / 100
    bmi = weight_kg / (height_m * height_m)
    # Math.round(bmi * 10) / 10 en JS redondea .5 siempre hacia arriba (no al
    # par mas cercano como el round() nativo de Python) — se replica a mano.
    bmi_redondeado = math.floor(bmi * 10 + 0.5) / 10

    return {"bmi": bmi_redondeado, "imc": bmi_redondeado, "errors": None}
