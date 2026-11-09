from pydantic import BaseModel
from typing import Any, Dict, List, Optional

class InputPayloadResponse(BaseModel):
    success: bool
    message: str
    received_keys: List[str]
    payload_summary: Optional[Dict[str, Any]] = None
