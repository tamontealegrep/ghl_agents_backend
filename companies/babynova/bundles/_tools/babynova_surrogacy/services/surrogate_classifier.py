"""
Reglas de negocio puras de clasificaciÃ³n de candidatas a gestante subrogada.
No sabe nada de HTTP. Port 1:1 del cÃ³digo JS del nodo "Surrogate Classification
Logic" del flujo de GHL, con los nombres de entrada/salida traducidos al
inglÃ©s a pedido del owner (2026-08-27) â€” la lÃ³gica de cada regla no cambiÃ³.
"""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from ..utils.parsing import is_present, normalize, parse_boolean, parse_flexible_date, parse_float

ALLOWED_CITIES = {
    "BOGOTA", "SOACHA", "ZIPAQUIRA", "CHIA", "MOSQUERA", "FUNZA", "CAJICA",
    "MADRID", "LA CALERA", "CALERA", "COTA", "FACATATIVA", "SIBATE",
}


_ELIGIBILITY_REASON_BY_REJECTION = {
    "Age": "age",
    "Timing": "timing",
    "City": "city",
    "EPS": "eps",
    "Children": "children",
    "C-Sections": "c_sections",
    "Preeclampsia": "preeclampsia",
    "BMI": "bmi",
    "Documentation": "documentation",
    "Drug Use": "drug_use",
}


def eligibility_fields(result: str) -> Tuple[str, str]:
    """Traduce la etiqueta de clasificación a los valores de los campos de GHL `eligibility_result` y `eligibility_reason`."""
    if result == "Approved":
        return "approved", "none"
    if result == "Inconclusive":
        return "inconclusive", "missing_data"
    rejection = result.partition("(")[2].rstrip(")")
    return "rejected", _ELIGIBILITY_REASON_BY_REJECTION.get(rejection, "none")


def classify_surrogate(data: Dict[str, Any]) -> str:
    """Aplica las 11 reglas de elegibilidad en orden y devuelve la etiqueta de clasificaciÃ³n resultante."""
    age = data.get("age")
    city = data.get("city")
    eps = data.get("eps")
    number_of_children = data.get("number_of_children")
    last_birth_date = data.get("last_birth_date")
    number_of_c_sections = data.get("number_of_c_sections")
    abortions = data.get("abortions")
    preeclampsia = data.get("preeclampsia")
    bmi = data.get("bmi")
    documentation = data.get("documentation")
    drug_use = data.get("drug_use")

    result: Optional[str] = None

    # 1. Edad
    if not is_present(age):
        result = "Inconclusive"
    else:
        num_age = parse_float(age)
        if num_age is None:
            result = "Inconclusive"
        elif num_age < 18:
            result = "Rejected (Timing)"
        elif num_age > 38:
            result = "Rejected (Age)"

    # 2. Ciudad
    if result is None:
        if not is_present(city):
            result = "Inconclusive"
        else:
            clean_city = normalize(city)
            if clean_city == "OTRO" or clean_city not in ALLOWED_CITIES:
                result = "Rejected (City)"

    # 3. EPS
    if result is None:
        eps_bool = parse_boolean(eps)
        if eps_bool is None:
            result = "Inconclusive"
        elif eps_bool is False:
            result = "Rejected (EPS)"

    # 4. Numero de Hijos
    if result is None:
        if not is_present(number_of_children):
            result = "Inconclusive"
        else:
            num_children = parse_float(number_of_children)
            if num_children is None:
                result = "Inconclusive"
            elif num_children < 1 or num_children > 4:
                result = "Rejected (Children)"

    # 5. Fecha del Ultimo Parto
    if result is None:
        if not is_present(last_birth_date):
            result = "Inconclusive"
        else:
            parsed_last_birth_date = parse_flexible_date(last_birth_date)
            if parsed_last_birth_date is None:
                result = "Inconclusive"
            else:
                now = datetime.now()
                months_diff = (now.year - parsed_last_birth_date.year) * 12 + (now.month - parsed_last_birth_date.month)
                if months_diff <= 12:
                    result = "Rejected (Timing)"

    # 6. Numero de Cesareas
    if result is None:
        if not is_present(number_of_c_sections):
            result = "Inconclusive"
        else:
            num_c_sections = parse_float(number_of_c_sections)
            if num_c_sections is None:
                result = "Inconclusive"
            elif num_c_sections > 2:
                result = "Rejected (C-Sections)"

    # 7. Abortos (dato recopilado, no es criterio de rechazo por si solo)
    if result is None:
        if parse_boolean(abortions) is None:
            result = "Inconclusive"

    # 8. Preeclampsia
    if result is None:
        preeclampsia_bool = parse_boolean(preeclampsia)
        if preeclampsia_bool is None:
            result = "Inconclusive"
        elif preeclampsia_bool is True:
            result = "Rejected (Preeclampsia)"

    # 9. IMC
    if result is None:
        if not is_present(bmi):
            result = "Inconclusive"
        else:
            num_bmi = parse_float(bmi)
            if num_bmi is None:
                result = "Inconclusive"
            elif num_bmi < 18.5 or num_bmi > 29.9:
                result = "Rejected (BMI)"

    # 10. Documentos
    if result is None:
        documentation_bool = parse_boolean(documentation)
        if documentation_bool is None:
            result = "Inconclusive"
        elif documentation_bool is False:
            result = "Rejected (Documentation)"

    # 11. Drogas
    if result is None:
        drug_use_bool = parse_boolean(drug_use)
        if drug_use_bool is None:
            result = "Inconclusive"
        elif drug_use_bool is True:
            result = "Rejected (Drug Use)"

    return result or "Approved"

