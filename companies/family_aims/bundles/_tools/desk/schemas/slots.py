from pydantic import BaseModel, Field


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


# TODO: migrate to what BabyNova already has (agent_backend/scheduling_schemas.py):
#   - drop end_co / end_local from Slot (a slot ends a fixed duration after its start);
#   - add `days` to SlotsResponse (agent_backend/slot_summary.summarize_days), before available_slots;
#   - update the desk endpoints, the Family Aims voice/text agent definitions, the shared
#     get_available_slots contract usage and their tests.
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
