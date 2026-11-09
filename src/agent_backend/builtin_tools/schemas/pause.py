from pydantic import BaseModel, Field


class PauseRequest(BaseModel):
    seconds: int = Field(..., ge=0, description="Number of seconds to wait before continuing.")


class PauseResponse(BaseModel):
    success: bool
    seconds: int
