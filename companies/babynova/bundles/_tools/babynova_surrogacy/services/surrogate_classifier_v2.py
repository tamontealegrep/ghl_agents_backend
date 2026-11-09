"""
Reglas de negocio puras de clasificacion de candidatas a gestante subrogada (version 2).

No sabe nada de HTTP. Reemplaza a surrogate_classifier.py para el agente
babynova_surrogate_questions_text_v2 y deja intacta la version 1 (la usa el
agente de voz).

Cambios respecto a la version 1:
  - Se elimina la regla de EPS.
  - La edad fuera de 18-38 siempre devuelve 'Rejected (Age)' (en la v1 los
    menores de 18 devolvian 'Rejected (Timing)').
  - Ultimo parto: depende del tipo de parto. Cesarea con menos de 18 meses o
    parto natural con menos de 12 meses -> 'Rejected (Timing)'.
  - Mas de 2 cesareas -> 'Rejected (C-Sections)'.
  - Los abortos solo se registran; la preeclampsia descarta.
  - La documentacion se evalua por tipo de documento: solo cedula de
    ciudadania o PPT.
  - Nueva regla de disponibilidad de tiempo para asistir a las consultas.
"""

from datetime import date
from typing import Any, Dict, Optional, Tuple

from ..utils.parsing import (
    is_present,
    normalize,
    parse_boolean,
    parse_flexible_date,
    parse_float,
)

ALLOWED_CITIES = {
    "BOGOTA", "SOACHA", "ZIPAQUIRA", "CHIA", "MOSQUERA", "FUNZA", "CAJICA",
    "MADRID", "LA CALERA", "CALERA", "COTA", "FACATATIVA", "SIBATE",
}

MIN_AGE = 18
MAX_AGE = 38
MIN_CHILDREN = 1
MAX_CHILDREN = 4
MAX_C_SECTIONS = 2
MIN_BMI = 18.5
MAX_BMI = 29.9

# Meses minimos entre el ultimo parto y hoy, segun el tipo de parto.
MIN_MONTHS_AFTER_C_SECTION = 18
MIN_MONTHS_AFTER_NATURAL_BIRTH = 12

_C_SECTION_VALUES = {"CSECTION", "C_SECTION", "CESAREA", "C-SECTION", "C SECTION", "CESAREAN", "CESARIA"}
_NATURAL_VALUES = {"NATURAL", "PARTO NATURAL", "VAGINAL", "NORMAL"}
_ALLOWED_DOCUMENTS = {"CEDULA_CIUDADANIA", "PPT"}

_ELIGIBILITY_REASON_BY_REJECTION = {
    "Age": "age",
    "Timing": "timing",
    "City": "city",
    "Children": "children",
    "C-Sections": "c_sections",
    "Preeclampsia": "preeclampsia",
    "BMI": "bmi",
    "Documentation": "documentation",
    "Drug Use": "drug_use",
    "Availability": "availability",
}


def eligibility_fields(result: str, missing_field: Optional[str] = None) -> Tuple[str, str]:
    """Traduce la etiqueta de clasificacion a los valores de los campos de GHL `eligibility_result` y `eligibility_reason`.

    Si el resultado es Inconclusive y se conoce el dato faltante, el motivo es `missing_data (<campo>)`.
    """
    if result == "Approved":
        return "approved", "none"
    if result == "Inconclusive":
        return "inconclusive", f"missing_data ({missing_field})" if missing_field else "missing_data"
    rejection = result.partition("(")[2].rstrip(")")
    return "rejected", _ELIGIBILITY_REASON_BY_REJECTION.get(rejection, "none")


def _parse_birth_type(value: Any) -> Optional[str]:
    """Devuelve 'c_section', 'natural' o None cuando el valor no se reconoce."""
    clean = normalize(value)
    if clean in _C_SECTION_VALUES:
        return "c_section"
    if clean in _NATURAL_VALUES:
        return "natural"
    return None


def _months_between(past: date, today: date) -> int:
    """Meses calendario entre dos fechas, contando solo anio y mes (igual que la v1)."""
    return (today.year - past.year) * 12 + (today.month - past.month)


def _check_last_birth(last_birth_date: Any, birth_type: Any, today: date) -> Tuple[Optional[str], Optional[str]]:
    """Evalua el ultimo parto.

    Devuelve (veredicto, campo_faltante): veredicto es 'Inconclusive', 'Rejected (Timing)' o None cuando cumple.
    birth_type es opcional: solo hace falta cuando el ultimo parto fue hace menos de 18 meses.
    """
    if not is_present(last_birth_date):
        return "Inconclusive", "last_birth_date"
    parsed = parse_flexible_date(last_birth_date)
    if parsed is None:
        return "Inconclusive", "last_birth_date"
    months = _months_between(parsed, today)
    if months >= MIN_MONTHS_AFTER_C_SECTION:
        return None, None
    # Menos de 18 meses: el tipo de parto decide.
    kind = _parse_birth_type(birth_type)
    if kind is None:
        return "Inconclusive", "birth_type"
    if kind == "c_section":
        return "Rejected (Timing)", None
    if months < MIN_MONTHS_AFTER_NATURAL_BIRTH:
        return "Rejected (Timing)", None
    return None, None


def classify_surrogate_v2(data: Dict[str, Any], today: Optional[date] = None) -> str:
    """Aplica las reglas de elegibilidad en orden y devuelve la etiqueta de clasificacion resultante."""
    return classify_surrogate_v2_detailed(data, today)[0]


def classify_surrogate_v2_detailed(data: Dict[str, Any], today: Optional[date] = None) -> Tuple[str, Optional[str]]:
    """Igual que classify_surrogate_v2, pero devuelve tambien el primer dato faltante cuando el resultado es Inconclusive."""
    today = today or date.today()

    # 1. Edad
    age = parse_float(data.get("age")) if is_present(data.get("age")) else None
    if age is None:
        return "Inconclusive", "age"
    if age < MIN_AGE or age > MAX_AGE:
        return "Rejected (Age)", None

    # 2. Ciudad
    if not is_present(data.get("city")):
        return "Inconclusive", "city"
    clean_city = normalize(data.get("city"))
    if clean_city == "OTRO" or clean_city not in ALLOWED_CITIES:
        return "Rejected (City)", None

    # 3. Numero de hijos
    children = parse_float(data.get("number_of_children")) if is_present(data.get("number_of_children")) else None
    if children is None:
        return "Inconclusive", "number_of_children"
    if children < MIN_CHILDREN or children > MAX_CHILDREN:
        return "Rejected (Children)", None

    # 4. Ultimo parto (fecha y tipo de parto)
    birth_verdict, birth_missing = _check_last_birth(data.get("last_birth_date"), data.get("birth_type"), today)
    if birth_verdict is not None:
        return birth_verdict, birth_missing

    # 5. Numero de cesareas
    c_sections = parse_float(data.get("number_of_c_sections")) if is_present(data.get("number_of_c_sections")) else None
    if c_sections is None:
        return "Inconclusive", "number_of_c_sections"
    if c_sections > MAX_C_SECTIONS:
        return "Rejected (C-Sections)", None

    # 6. Abortos: dato que se registra, no es criterio de rechazo por si solo
    if parse_boolean(data.get("abortions")) is None:
        return "Inconclusive", "abortions"

    # 7. Preeclampsia
    preeclampsia = parse_boolean(data.get("preeclampsia"))
    if preeclampsia is None:
        return "Inconclusive", "preeclampsia"
    if preeclampsia is True:
        return "Rejected (Preeclampsia)", None

    # 8. IMC
    bmi = parse_float(data.get("bmi")) if is_present(data.get("bmi")) else None
    if bmi is None:
        return "Inconclusive", "bmi"
    if bmi < MIN_BMI or bmi > MAX_BMI:
        return "Rejected (BMI)", None

    # 9. Documento: solo cedula de ciudadania o PPT
    if not is_present(data.get("document_type")):
        return "Inconclusive", "document_type"
    document = normalize(data.get("document_type")).replace(" ", "_")
    if document not in _ALLOWED_DOCUMENTS:
        return "Rejected (Documentation)", None

    # 10. Sustancias psicoactivas
    drug_use = parse_boolean(data.get("drug_use"))
    if drug_use is None:
        return "Inconclusive", "drug_use"
    if drug_use is True:
        return "Rejected (Drug Use)", None

    # 11. Disponibilidad de tiempo para las consultas
    availability = parse_boolean(data.get("availability"))
    if availability is None:
        return "Inconclusive", "availability"
    if availability is False:
        return "Rejected (Availability)", None

    return "Approved", None
