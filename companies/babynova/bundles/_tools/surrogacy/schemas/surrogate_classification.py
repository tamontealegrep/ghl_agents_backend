from typing import Any

from pydantic import BaseModel, Field


class SurrogateClassificationRequest(BaseModel):
    age: Any | None = Field(default=None, examples=["25"])
    city: Any | None = Field(default=None, examples=["Bogota"])
    nationality: Any | None = Field(
        default=None, examples=["COL"], description="Solo se registra; no es criterio de rechazo."
    )
    number_of_children: Any | None = Field(default=None, examples=["2"])
    last_birth_date: Any | None = Field(
        default=None, examples=["2023-01-15"], description="YYYY-MM-DD o YYYY/MM/DD."
    )
    birth_type: Any | None = Field(
        default=None,
        examples=["csection", "natural"],
        description="Obligatorio solo si el ultimo parto fue hace menos de 18 meses.",
    )
    number_of_c_sections: Any | None = Field(default=None, examples=["1"])
    abortions: Any | None = Field(default=None, examples=["no"])
    preeclampsia: Any | None = Field(default=None, examples=["no"])
    bmi: Any | None = Field(default=None, examples=["22.0"])
    document_type: Any | None = Field(default=None, examples=["cedula_ciudadania", "ppt", "other"])
    eps_active_affiliation: Any | None = Field(default=None, examples=["si"])
    drug_use: Any | None = Field(default=None, examples=["no"])
    availability: Any | None = Field(default=None, examples=["si"])
    voice: Any | None = Field(
        default=None,
        examples=["si"],
        description=(
            "Llamada de voz. Con verdadero no se evalua el documento ni la EPS (document_type y "
            "eps_active_affiliation se ignoran) y quien cumple el resto queda 'Pre-approved'. "
            "Falso o ausente: clasificacion completa."
        ),
    )


class SurrogateClassificationResponse(BaseModel):
    success: bool
    result: str | None = None
    eligibility_result: str | None = Field(default=None, description="approved, pre-approved (solo con voice), rejected o inconclusive.")
    not_eligibility_reason: str | None = Field(
        default=None,
        description="Motivo del rechazo, 'missing_data (<campo>)' con el primer dato faltante, o none.",
    )
    errors: str | None = None
