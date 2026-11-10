"""Request and response models of the scheduling tools, shared by every company."""

from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_TZ = "America/Bogota"
_CALENDAR = "Required. Calendar key (see GET /calendars), e.g. 'FT'. A call without it fails."


class SlotsRequest(BaseModel):
    iana_timezone: str = Field(default=DEFAULT_TZ, examples=["America/Bogota"], description="User timezone, e.g. 'America/Bogota'.")
    calendar_type: str | None = Field(default=None, examples=["FT"], description=_CALENDAR)


class Slot(BaseModel):
    start_co: str
    end_co: str
    start_local: str
    end_local: str


class SlotsResponse(BaseModel):
    success: bool
    iana_timezone: str
    available_slots: list[Slot]
    errors: str | None = None


class BookAppointmentRequest(BaseModel):
    start_date: str = Field(examples=["2026-08-28T09:00:00-05:00"])
    duration: str | None = Field(default="10", examples=["10"])
    contact_name: str = Field(examples=["Maria Perez"])
    contact_email: str = Field(examples=["maria.perez@example.com"])
    contact_phone: str = Field(examples=["+573001234567"])
    iana_timezone: str | None = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: str | None = Field(default=None, examples=["FT"], description=_CALENDAR)


class BookAppointmentResponse(BaseModel):
    success: bool
    reason: str | None = None
    event_id: str | None = None
    event_link: str | None = None
    meet_link: str | None = None
    errors: str | None = None


class FindAppointmentRequest(BaseModel):
    contact_name: str | None = Field(default="", examples=["John Doe"])
    contact_phone: str | None = Field(default="", examples=["+573001234567"])
    contact_email: str | None = Field(default="", examples=["john@example.com"])
    iana_timezone: str | None = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: str | None = Field(default=None, examples=["FT"], description=_CALENDAR)


class AppointmentInfo(BaseModel):
    event_id: str
    summary: str
    start_time: str
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None


class FindAppointmentResponse(BaseModel):
    success: bool
    appointments: list[AppointmentInfo] = Field(default_factory=list)
    errors: str | None = None


class CancelAppointmentRequest(BaseModel):
    event_id: str = Field(examples=["_60q30c1060o30e1g60o30hc160o30jbi60o30h9g60o30c1g60o3..."])
    iana_timezone: str | None = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: str | None = Field(default=None, examples=["FT"], description=_CALENDAR)


class CancelAppointmentResponse(BaseModel):
    success: bool
    message: str | None = None
    errors: str | None = None


class EditAppointmentRequest(BaseModel):
    event_id: str = Field(examples=["_60q30c1060o30e1g60o30hc160o30jbi60o30h9g60o30c1g60o3..."])
    new_start_date: str | None = Field(default=None, examples=["2026-08-28T10:00:00-05:00"])
    new_duration: str | None = Field(default=None, examples=["30"])
    iana_timezone: str | None = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: str | None = Field(default=None, examples=["FT"], description=_CALENDAR)


class EditAppointmentResponse(BaseModel):
    success: bool
    message: str | None = None
    new_start_time: str | None = None
    new_duration: str | None = None
    errors: str | None = None
