
from pydantic import BaseModel, Field


class TimeNowRequest(BaseModel):
    # Field name matches shared/tool_contracts/time_now_contract_es.yaml
    # (agent_runtime), the contract 6 different agents' DSL content already
    # declares for this tool — was "timezone", which meant every agent's own
    # "iana_timezone = [user_timezone]" DO-line binding could never match
    # this field mechanically. See router.py's family_aims alias comment for
    # the routing half of this same bug.
    iana_timezone: str = Field(default="UTC", examples=["America/Bogota"])


class TimeNowResponse(BaseModel):
    success: bool
    iana_timezone: str
    now: str | None = None
    calendar: str | None = None
    errors: str | None = None
