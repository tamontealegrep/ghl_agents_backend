from typing import Any

from pydantic import BaseModel


class InputPayloadResponse(BaseModel):
    success: bool
    message: str
    received_keys: list[str]
    payload_summary: dict[str, Any] | None = None
