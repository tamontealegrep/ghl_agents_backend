from typing import List, Optional

from pydantic import BaseModel, Field


class SlotsRequest(BaseModel):
    calendar_type: str = Field(
        default="IVF",
        examples=["IVF", "SUR"],
        description="Calendar key (see GET /calendars), e.g. 'IVF' or 'SUR'.",
    )
    iana_timezone: str = Field(
        default="America/Bogota",
        examples=["America/Bogota"],
        description="Zona horaria del cliente, ej. 'America/Bogota'.",
    )


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
