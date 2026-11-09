from typing import List, Optional

from pydantic import BaseModel, Field


class BookAppointmentRequest(BaseModel):
    calendar_type: str = Field(
        default="IVF",
        examples=["IVF", "SUR"],
        description="Calendar key (see GET /calendars), e.g. 'IVF' or 'SUR'.",
    )
    start_date: str = Field(examples=["2026-08-28T09:00:00-05:00"])
    duration: str = Field(examples=["20"])
    contact_name: str = Field(examples=["Maria Perez"])
    contact_email: str = Field(examples=["maria.perez@correo-cliente.com"])
    contact_phone: str = Field(examples=["+573001234567"])
    language: str = Field(examples=["ES"])
    iana_timezone: str = Field(examples=["America/Bogota"])


class BookAppointmentResponse(BaseModel):
    success: bool
    reason: Optional[str] = None
    event_id: Optional[str] = None
    event_link: Optional[str] = None
    meet_link: Optional[str] = None
    errors: Optional[str] = None


class FindAppointmentRequest(BaseModel):
    contact_name: str = Field(default="", examples=["John Doe"])
    contact_email: str = Field(default="", examples=["john@example.com"])
    calendar_type: str = Field(examples=["IVF"], description="Calendar key (see GET /calendars), e.g. 'IVF' or 'SUR'")
    iana_timezone: str = Field(default="America/Bogota", examples=["America/Bogota"])
    language: str = Field(default="ES", examples=["ES", "EN", "PT"])


class AppointmentInfo(BaseModel):
    event_id: str
    summary: str
    start_time: str
    calendar_type: str  # "IVF" o "SUR"


class FindAppointmentResponse(BaseModel):
    success: bool
    appointments: List[AppointmentInfo] = Field(default_factory=list)
    errors: Optional[str] = None


class CancelAppointmentRequest(BaseModel):
    event_id: str = Field(examples=["_60q30c1060o30e1g60o30hc160o30jbi60o30h9g60o30c1g60o3..."])
    calendar_type: str = Field(examples=["IVF"], description="Calendar key (see GET /calendars), e.g. 'IVF' or 'SUR'")
    iana_timezone: str = Field(default="America/Bogota", examples=["America/Bogota"])


class CancelAppointmentResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    errors: Optional[str] = None


class EditAppointmentRequest(BaseModel):
    event_id: str = Field(examples=["_60q30c1060o30e1g60o30hc160o30jbi60o30h9g60o30c1g60o3..."])
    calendar_type: str = Field(examples=["IVF"], description="Calendar key (see GET /calendars), e.g. 'IVF' or 'SUR'")
    new_start_date: Optional[str] = Field(default=None, examples=["2026-08-28T10:00:00-05:00"])
    new_duration: Optional[str] = Field(default=None, examples=["30"])
    iana_timezone: str = Field(default="America/Bogota", examples=["America/Bogota"])
    language: str = Field(default="ES", examples=["ES", "EN", "PT"])


class EditAppointmentResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    new_start_time: Optional[str] = None
    new_duration: Optional[str] = None
    errors: Optional[str] = None


# --- GHL: resolve event link ---
class ResolveEventLinkRequest(BaseModel):
    calendar_type: str = Field(
        default="IVF",
        examples=["IVF", "SUR"],
        description="Calendar key (see GET /calendars), e.g. 'IVF' or 'SUR'",
    )
    start_date: str = Field(examples=["2026-08-28T09:00:00-05:00"])
    iana_timezone: str = Field(default="America/Bogota", examples=["America/Bogota"])
    contact_name: str = Field(default="", examples=["Maria Perez"])
    meet_link: Optional[str] = Field(default=None, examples=["https://meet.google.com/xyz-abcd-efg"])


class ResolveEventLinkResponse(BaseModel):
    success: bool
    event_link: Optional[str] = None
    errors: Optional[str] = None
