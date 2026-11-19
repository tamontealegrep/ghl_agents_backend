from typing import Any

from pydantic import BaseModel, Field


class DonorClassificationRequest(BaseModel):
    age: Any | None = Field(default=None, examples=["25"])
    city: Any | None = Field(default=None, examples=["Bogota"])
    nationality: Any | None = Field(default=None, examples=["COL"], description="ISO 3166-1 alfa-3.")
    sexual_life: Any | None = Field(default=None, examples=["si"], description="Ya inicio su vida sexual.")
    height_cm: Any | None = Field(default=None, examples=["165"])
    bmi: Any | None = Field(default=None, examples=["22.0"])
    drug_use: Any | None = Field(default=None, examples=["no"])
    pregnancies: Any | None = Field(default=None, examples=["no"], description="Solo se registra.")
    abortions: Any | None = Field(default=None, examples=["no"], description="Solo se registra.")
    lactating: Any | None = Field(default=None, examples=["no"], description="Solo se registra.")
    document_type: Any | None = Field(default=None, examples=["cedula_ciudadania", "ppt", "other"])
    eps_active_affiliation: Any | None = Field(default=None, examples=["si"])


class DonorClassificationResponse(BaseModel):
    success: bool
    result: str | None = None
    eligibility_result: str | None = Field(
        default=None, description="eligible, to_validate, not_eligible o incomplete."
    )
    not_eligibility_reason: str | None = Field(
        default=None,
        description="Criterio incumplido, '<criterio>_to_validate', 'missing_data (<campo>)' con el primer dato faltante, o none.",
    )
    errors: str | None = None
