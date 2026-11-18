"""
Reglas de negocio puras de precalificacion de candidatas a donante de ovulos (BabyNova).

No sabe nada de HTTP. Endpoint /donor-classification.

Resultados:
  - 'Approved'.
  - 'Inconclusive': falta el primer dato necesario (se devuelve cual).
  - 'Rejected (<criterio>)': incumple un criterio de exclusion.
  - 'To Validate (<criterio>)': caso limite que revisa el equipo; no se rechaza.

Orden de evaluacion: edad, ciudad, nacionalidad, vida sexual, estatura, IMC, drogas, embarazos,
abortos, lactancia, documento y EPS. Nacionalidad, embarazos, abortos y lactancia solo se registran.
"""

from typing import Any

from ..utils.parsing import is_present, normalize, parse_boolean, parse_float

ALLOWED_CITIES = {
    "BOGOTA",
    "CAJICA",
    "ZIPAQUIRA",
    "SOPO",
    "LA CALERA",
    "CALERA",
    "MOSQUERA",
    "FUNZA",
    "FACATATIVA",
    "COTA",
    "SIBATE",
    "SOACHA",
    "TENJO",
    "TABIO",
    "MADRID",
    "TOCANCIPA",
}

MIN_AGE = 20
MAX_AGE = 32
# Una edad de 19 o 33 anios no la decide el manual: la valida el equipo. Fuera de 19-33 se rechaza.
REVIEW_MIN_AGE = 19
REVIEW_MAX_AGE = 33

MIN_HEIGHT_CM = 150.0

MIN_BMI = 17.9
MAX_BMI = 27.9
# Fuera de 17.0-28.0 se rechaza; entre estos limites y el rango aceptado la valida el equipo.
REJECT_BMI_BELOW = 17.0
REJECT_BMI_ABOVE = 28.0

_ALLOWED_DOCUMENTS = {"CEDULA_CIUDADANIA", "PPT"}

_ELIGIBILITY_REASON_BY_REJECTION = {
    "Age": "age",
    "City": "city",
    "Sexual Life": "sexual_life",
    "Height": "height",
    "BMI": "bmi",
    "Drug Use": "drug_use",
    "Documentation": "documentation",
    "EPS": "eps",
}


def eligibility_fields(result: str, missing_field: str | None = None) -> tuple[str, str]:
    """Traduce la etiqueta a los valores de los campos de GHL `donor_eligibility_result` y `donor_not_eligibility_reason`.

    Approved -> eligible/none; To Validate -> to_validate/<criterio>_to_validate;
    Inconclusive -> incomplete/missing_data (<campo>); Rejected -> not_eligible/<criterio>.
    """
    if result == "Approved":
        return "eligible", "none"
    if result == "Inconclusive":
        return "incomplete", f"missing_data ({missing_field})" if missing_field else "missing_data"
    label = result.partition("(")[2].rstrip(")")
    if result.startswith("To Validate"):
        return "to_validate", f"{label.lower().replace(' ', '_')}_to_validate"
    return "not_eligible", _ELIGIBILITY_REASON_BY_REJECTION.get(label, "none")


def classify_donor(data: dict[str, Any]) -> str:
    """Aplica las reglas de elegibilidad en orden y devuelve la etiqueta de clasificacion resultante."""
    return classify_donor_detailed(data)[0]


def classify_donor_detailed(data: dict[str, Any]) -> tuple[str, str | None]:
    """Igual que classify_donor, pero devuelve tambien el primer dato faltante cuando el resultado es Inconclusive."""
    to_validate: str | None = None

    # 1. Edad: 20-32 pasa, 19 y 33 los valida el equipo, el resto se rechaza
    age = parse_float(data.get("age")) if is_present(data.get("age")) else None
    if age is None:
        return "Inconclusive", "age"
    if age < REVIEW_MIN_AGE or age > REVIEW_MAX_AGE:
        return "Rejected (Age)", None
    if age < MIN_AGE or age > MAX_AGE:
        to_validate = to_validate or "To Validate (Age)"

    # 2. Ciudad
    if not is_present(data.get("city")):
        return "Inconclusive", "city"
    clean_city = normalize(data.get("city"))
    if clean_city == "OTRO" or clean_city not in ALLOWED_CITIES:
        return "Rejected (City)", None

    # 3. Nacionalidad: solo se registra
    if not is_present(data.get("nationality")):
        return "Inconclusive", "nationality"

    # 4. Vida sexual iniciada
    sexual_life = parse_boolean(data.get("sexual_life"))
    if sexual_life is None:
        return "Inconclusive", "sexual_life"
    if sexual_life is False:
        return "Rejected (Sexual Life)", None

    # 5. Estatura (cm)
    height = parse_float(data.get("height_cm")) if is_present(data.get("height_cm")) else None
    if height is None:
        return "Inconclusive", "height_cm"
    if height < MIN_HEIGHT_CM:
        return "Rejected (Height)", None

    # 6. IMC: 17.9-27.9 pasa, por debajo de 17.0 o por encima de 28.0 se rechaza, en medio lo valida el equipo
    bmi = parse_float(data.get("bmi")) if is_present(data.get("bmi")) else None
    if bmi is None:
        return "Inconclusive", "bmi"
    if bmi < REJECT_BMI_BELOW or bmi > REJECT_BMI_ABOVE:
        return "Rejected (BMI)", None
    if bmi < MIN_BMI or bmi > MAX_BMI:
        to_validate = to_validate or "To Validate (BMI)"

    # 7. Sustancias psicoactivas
    drug_use = parse_boolean(data.get("drug_use"))
    if drug_use is None:
        return "Inconclusive", "drug_use"
    if drug_use is True:
        return "Rejected (Drug Use)", None

    # 8 a 10. Embarazos previos, abortos y lactancia: datos que se registran, no son criterio de rechazo
    for field in ("pregnancies", "abortions", "lactating"):
        if parse_boolean(data.get(field)) is None:
            return "Inconclusive", field

    # 11. Documento: solo cedula de ciudadania o PPT
    if not is_present(data.get("document_type")):
        return "Inconclusive", "document_type"
    document = normalize(data.get("document_type")).replace(" ", "_")
    if document not in _ALLOWED_DOCUMENTS:
        return "Rejected (Documentation)", None

    # 12. Afiliacion activa a una EPS (no se verifica en ADRES en esta etapa): sin afiliacion no pasa
    eps_active = parse_boolean(data.get("eps_active_affiliation"))
    if eps_active is None:
        return "Inconclusive", "eps_active_affiliation"
    if eps_active is False:
        return "Rejected (EPS)", None

    return to_validate or "Approved", None
