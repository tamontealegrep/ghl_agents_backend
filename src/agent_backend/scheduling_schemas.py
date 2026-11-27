"""Request and response models of the scheduling tools, shared by every company."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

DEFAULT_TZ = "America/Bogota"
_CALENDAR = "Required. Calendar key (see GET /calendars), e.g. 'FT'. A call without it fails."


class SlotsRequest(BaseModel):
    iana_timezone: str = Field(
        default=DEFAULT_TZ, examples=["America/Bogota"], description="User timezone, e.g. 'America/Bogota'."
    )
    calendar_type: str | None = Field(default=None, examples=["FT"], description=_CALENDAR)


class Slot(BaseModel):
    start_co: str
    start_local: str


class ContinuousRange(BaseModel):
    type: Literal["continuous_range"] = "continuous_range"
    first_start: str = Field(examples=["14:00"], description="First start time (HH:MM) of the range.")
    last_start: str = Field(examples=["16:30"], description="Last start time (HH:MM) of the range, included.")
    every_minutes: int = Field(examples=[10], description="There is a bookable start time every this many minutes.")


class SingleSlot(BaseModel):
    type: Literal["single_slot"] = "single_slot"
    start: str = Field(examples=["17:00"], description="The only bookable start time (HH:MM) in this block.")


class SlotDay(BaseModel):
    date: str = Field(examples=["2026-11-27"])
    label: str = Field(examples=["Friday, November 27"])
    timezone: str = Field(examples=["Europe/Madrid"], description="IANA time zone of date, label and times (the contact's).")
    utc_offset: str = Field(examples=["+01:00"], description="UTC offset of that zone on that day.")
    parts_of_day: list[Literal["morning", "afternoon", "evening", "night"]] = Field(examples=[["afternoon"]])
    times: list[ContinuousRange | SingleSlot]
    slot_count: int


class SlotsResponse(BaseModel):
    success: bool
    iana_timezone: str
    days: list[SlotDay] = Field(
        default_factory=list,
        description="Summary of available_slots by day (date, English label, parts_of_day, typed time blocks). Say the days from here.",
    )
    available_slots: list[Slot]
    errors: str | None = None


class BookAppointmentRequest(BaseModel):
    start_date: str = Field(examples=["2026-08-28T09:00:00-05:00"])
    duration: str | None = Field(default="10", examples=["10"])
    contact_name: str | None = Field(
        default=None,
        examples=["Maria Perez"],
        description="Optional: when missing, it is read from the GHL contact (contact_id).",
    )
    contact_email: str | None = Field(
        default=None,
        examples=["maria.perez@example.com"],
        description="Optional: when missing, it is read from the GHL contact (contact_id).",
    )
    contact_phone: str | None = Field(
        default=None,
        examples=["+573001234567"],
        description="Optional: when missing, it is read from the GHL contact (contact_id).",
    )
    contact_id: str | None = Field(
        default=None,
        examples=["F2FikaF1uvDozXJIcRB1"],
        description=(
            "Required. GHL contact the appointment belongs to: the conversation's contact. The tool fails without "
            "it; it never looks a contact up by e-mail or phone."
        ),
    )
    iana_timezone: str | None = Field(default=DEFAULT_TZ, examples=["America/Bogota"])
    calendar_type: str | None = Field(default=None, examples=["FT"], description=_CALENDAR)
    time_format: str | None = Field(
        default="12h",
        examples=["12h", "24h"],
        description=(
            "How appointment_time is returned: '12h' (08:50 AM, the default) or '24h' (08:50, 14:05). Anything else "
            "is read as '12h'."
        ),
    )


class BookAppointmentResponse(BaseModel):
    success: bool
    reason: str | None = None
    event_id: str | None = None
    event_link: str | None = None
    meet_link: str | None = None
    appointment_date: str | None = Field(
        default=None,
        examples=["Tuesday, November 16, 2026"],
        description=(
            "Date of the booked appointment in English, in the contact's time zone. The agent translates it to the "
            "language it speaks before saving it."
        ),
    )
    appointment_time: str | None = Field(
        default=None,
        examples=["08:50 AM", "14:05"],
        description=(
            "Time of the booked appointment in the contact's time zone, in the format asked with time_format. The "
            "agent adapts AM/PM to the language it speaks before saving it."
        ),
    )
    errors: str | None = None


class FindAppointmentRequest(BaseModel):
    contact_name: str | None = Field(default="", examples=["John Doe"])
    contact_phone: str | None = Field(default="", examples=["+573001234567"])
    contact_email: str | None = Field(default="", examples=["john@example.com"])
    contact_id: str | None = Field(
        default=None,
        examples=["F2FikaF1uvDozXJIcRB1"],
        description=(
            "Required. GHL contact the appointment belongs to: the conversation's contact. The tool fails without "
            "it; it never looks a contact up by e-mail or phone."
        ),
    )
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
