
from pydantic import BaseModel, Field


class CallbackRequest(BaseModel):
    contact_name: str | None = Field(default=None, examples=["Maria Perez"])
    contact_phone: str | None = Field(default=None, examples=["+573001234567"])
    contact_email: str | None = Field(default=None, examples=["maria@example.com"])
    reason: str | None = Field(default=None, examples=["no_availability"])
    context: str | None = Field(default=None, examples=["No hubo cupos disponibles en los proximos 14 dias"])
    preferred_days: str | list[str] | None = Field(default=None, examples=["weekdays", "monday,wednesday"])
    preferred_time_window: str | None = Field(default=None, examples=["morning"])
    iana_timezone: str | None = Field(default=None, examples=["America/Bogota"])


class CallbackRequestResponse(BaseModel):
    success: bool
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    reason: str | None = None
    context: str | None = None
    preferred_days: list[str] | None = None
    preferred_time_window: str | None = None
    iana_timezone: str | None = None
    errors: str | None = None
