from typing import Any, Optional

from pydantic import BaseModel, Field


class SurrogateClassificationV2Request(BaseModel):
    age: Optional[Any] = Field(default=None, examples=["25"])
    city: Optional[Any] = Field(default=None, examples=["Bogota"])
    nationality: Optional[Any] = Field(default=None, examples=["COL"], description="Solo se registra; no es criterio de rechazo.")
    number_of_children: Optional[Any] = Field(default=None, examples=["2"])
    last_birth_date: Optional[Any] = Field(default=None, examples=["2023-01-15"], description="YYYY-MM-DD o YYYY/MM/DD.")
    birth_type: Optional[Any] = Field(default=None, examples=["csection", "natural"], description="Obligatorio solo si el ultimo parto fue hace menos de 18 meses.")
    number_of_c_sections: Optional[Any] = Field(default=None, examples=["1"])
    abortions: Optional[Any] = Field(default=None, examples=["no"])
    preeclampsia: Optional[Any] = Field(default=None, examples=["no"])
    bmi: Optional[Any] = Field(default=None, examples=["22.0"])
    document_type: Optional[Any] = Field(default=None, examples=["cedula_ciudadania", "ppt", "other"])
    drug_use: Optional[Any] = Field(default=None, examples=["no"])
    availability: Optional[Any] = Field(default=None, examples=["si"])


class SurrogateClassificationV2Response(BaseModel):
    success: bool
    result: Optional[str] = None
    eligibility_result: Optional[str] = Field(default=None, description="approved, rejected o inconclusive.")
    eligibility_reason: Optional[str] = Field(default=None, description="Motivo del rechazo, 'missing_data (<campo>)' con el primer dato faltante, o none.")
    errors: Optional[str] = None
