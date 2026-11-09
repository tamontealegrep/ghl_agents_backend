from typing import Any, Optional

from pydantic import BaseModel, Field


class SurrogateClassificationRequest(BaseModel):
    age: Optional[Any] = Field(default=None, examples=["25"])
    city: Optional[Any] = Field(default=None, examples=["Bogota"])
    eps: Optional[Any] = Field(default=None, examples=["si"])
    number_of_children: Optional[Any] = Field(default=None, examples=["2"])
    last_birth_date: Optional[Any] = Field(default=None, examples=["2015-01-15"], description="YYYY-MM-DD o YYYY/MM/DD.")
    number_of_c_sections: Optional[Any] = Field(default=None, examples=["1"])
    abortions: Optional[Any] = Field(default=None, examples=["no"])
    preeclampsia: Optional[Any] = Field(default=None, examples=["no"])
    bmi: Optional[Any] = Field(default=None, examples=["22.0"])
    documentation: Optional[Any] = Field(default=None, examples=["si"])
    drug_use: Optional[Any] = Field(default=None, examples=["no"])


class SurrogateClassificationResponse(BaseModel):
    success: bool
    result: Optional[str] = None
    eligibility_result: Optional[str] = Field(default=None, description="approved, rejected o inconclusive.")
    eligibility_reason: Optional[str] = Field(default=None, description="Motivo del rechazo, missing_data o none.")
    errors: Optional[str] = None
