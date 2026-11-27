from pydantic import BaseModel, Field

from agent_backend.scheduling_schemas import SlotDay


class SlotsRequest(BaseModel):
    calendar_type: str = Field(
        default="FT",
        examples=["FT"],
        description="Calendar key (see GET /calendars), e.g. 'FT'.",
    )
    iana_timezone: str = Field(
        default="America/Bogota",
        examples=["America/Bogota"],
        description="Zona horaria del cliente, ej. 'America/Bogota'.",
    )


class Slot(BaseModel):
    start_co: str
    start_local: str


class SlotsResponse(BaseModel):
    success: bool
    iana_timezone: str
    days: list[SlotDay] = Field(
        default_factory=list,
        description=(
            "Summary of available_slots by day, in the contact's time zone (date, English label, parts_of_day, "
            "typed time blocks). Say the days from here."
        ),
    )
    available_slots: list[Slot]
    errors: str | None = None
