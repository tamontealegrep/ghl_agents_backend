from typing import Any, Optional

from pydantic import BaseModel, Field


class CheckDaysElapsedRequest(BaseModel):
    date: Optional[Any] = Field(default=None, examples=["2024/06/15"])
    days: Optional[Any] = Field(default=None, examples=[365])


class CheckDaysElapsedResponse(BaseModel):
    success: bool
    elapsed: Optional[bool] = None
    days_elapsed: Optional[int] = None
    errors: Optional[str] = None
