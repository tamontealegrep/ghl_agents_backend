from typing import Any, Optional

from pydantic import BaseModel, Field


class CalculateBmiRequest(BaseModel):
    weight_kg: Optional[Any] = Field(default=None, examples=["70"])
    height_cm: Optional[Any] = Field(default=None, examples=["175"])


class CalculateBmiResponse(BaseModel):
    success: bool
    bmi: Optional[float] = None
    imc: Optional[float] = None
    errors: Optional[str] = None
