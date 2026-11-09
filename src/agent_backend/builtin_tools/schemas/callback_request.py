from typing import List, Optional, Union

from pydantic import BaseModel, Field


class CallbackRequest(BaseModel):
    contact_name: Optional[str] = Field(default=None, examples=["Maria Perez"])
    contact_phone: Optional[str] = Field(default=None, examples=["+573001234567"])
    contact_email: Optional[str] = Field(default=None, examples=["maria@example.com"])
    reason: Optional[str] = Field(default=None, examples=["no_availability"])
    context: Optional[str] = Field(default=None, examples=["No hubo cupos disponibles en los proximos 14 dias"])
    preferred_days: Optional[Union[str, List[str]]] = Field(default=None, examples=["weekdays", "monday,wednesday"])
    preferred_time_window: Optional[str] = Field(default=None, examples=["morning"])
    iana_timezone: Optional[str] = Field(default=None, examples=["America/Bogota"])


class CallbackRequestResponse(BaseModel):
    success: bool
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    reason: Optional[str] = None
    context: Optional[str] = None
    preferred_days: Optional[List[str]] = None
    preferred_time_window: Optional[str] = None
    iana_timezone: Optional[str] = None
    errors: Optional[str] = None
