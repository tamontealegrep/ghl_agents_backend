"""Request and response models of the scheduling tools, shared by every company."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

DEFAULT_TZ = "America/Bogota"
_CALENDAR = "Required. Calendar key (see GET /calendars), e.g. 'FT'. A call without it fails."


class SlotsRequest(BaseModel):
    iana_timezone: str = Field(default=DEFAULT_TZ, examples=["America/Bogota"], description="User timezone, e.g. 'America/Bogota'.")
    calendar_type: Optional[str] = Field(default=None, examples=["FT"], description=_CALENDAR)


class Slot(BaseModel):
    start_co: str
    end_co: str
    start_local: str
    end_local: str


class SlotsResponse(BaseModel):
    success: bool
    iana_timezone: str
    available_slots: List[Slot]
    errors: Optional[str] = None


class BookAppointmentRequest(BaseModel):
    start_date: str = Field(examples=["2026-08-28T09:00:00-05:00"])
    duration: Optional[str] = Field(default="10", examples=["10"])
    contact_name: str = Field(examples=["Maria Perez"])
    contact_email: str = Field(examples=["maria.perez@example.com"])
    contact_phone: str = Field(examples=["+573001234567"])
    iana_timezone: Optional[str] = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: Optional[str] = Field(default=None, examples=["FT"], description=_CALENDAR)


class BookAppointmentResponse(BaseModel):
    success: bool
    reason: Optional[str] = None
    event_id: Optional[str] = None
    event_link: Optional[str] = None
    meet_link: Optional[str] = None
    errors: Optional[str] = None


class FindAppointmentRequest(BaseModel):
    contact_name: Optional[str] = Field(default="", examples=["John Doe"])
    contact_phone: Optional[str] = Field(default="", examples=["+573001234567"])
    contact_email: Optional[str] = Field(default="", examples=["john@example.com"])
    iana_timezone: Optional[str] = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: Optional[str] = Field(default=None, examples=["FT"], description=_CALENDAR)


class AppointmentInfo(BaseModel):
    event_id: str
    summary: str
    start_time: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None


class FindAppointmentResponse(BaseModel):
    success: bool
    appointments: List[AppointmentInfo] = Field(default_factory=list)
    errors: Optional[str] = None


class CancelAppointmentRequest(BaseModel):
    event_id: str = Field(examples=["_60q30c1060o30e1g60o30hc160o30jbi60o30h9g60o30c1g60o3..."])
    iana_timezone: Optional[str] = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: Optional[str] = Field(default=None, examples=["FT"], description=_CALENDAR)


class CancelAppointmentResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    errors: Optional[str] = None


class EditAppointmentRequest(BaseModel):
    event_id: str = Field(examples=["_60q30c1060o30e1g60o30hc160o30jbi60o30h9g60o30c1g60o3..."])
    new_start_date: Optional[str] = Field(default=None, examples=["2026-08-28T10:00:00-05:00"])
    new_duration: Optional[str] = Field(default=None, examples=["30"])
    iana_timezone: Optional[str] = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: Optional[str] = Field(default=None, examples=["FT"], description=_CALENDAR)


class EditAppointmentResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    new_start_time: Optional[str] = None
    new_duration: Optional[str] = None
    errors: Optional[str] = None
