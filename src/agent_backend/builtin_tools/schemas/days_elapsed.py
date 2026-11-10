from typing import Any

from pydantic import BaseModel, Field


class CheckDaysElapsedRequest(BaseModel):
    date: Any | None = Field(default=None, examples=["2024/06/15"])
    days: Any | None = Field(default=None, examples=[365])


class CheckDaysElapsedResponse(BaseModel):
    success: bool
    elapsed: bool | None = None
    days_elapsed: int | None = None
    errors: str | None = None
