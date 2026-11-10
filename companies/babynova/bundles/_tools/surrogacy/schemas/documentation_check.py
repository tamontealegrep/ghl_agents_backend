from typing import List, Optional, Union

from pydantic import BaseModel, Field


class CheckDocumentationRequest(BaseModel):
    nationality: Optional[str] = Field(default=None, examples=["COL"])
    document_type: Optional[Union[str, List[str]]] = Field(default=None, examples=["cedula_ciudadania", "ppt,pasaporte"])


class CheckDocumentationResponse(BaseModel):
    success: bool
    approved: Optional[bool] = None
    reason: Optional[str] = None
    normalized_documents: Optional[List[str]] = None
    errors: Optional[str] = None
