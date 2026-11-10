from typing import Any

from pydantic import BaseModel, Field


class CalculateBmiRequest(BaseModel):
    weight_kg: Any | None = Field(default=None, examples=["70"])
    height_cm: Any | None = Field(default=None, examples=["175"])


class CalculateBmiResponse(BaseModel):
    success: bool
    bmi: float | None = None
    imc: float | None = None
    errors: str | None = None
