from pydantic import BaseModel, Field


class CheckDocumentationRequest(BaseModel):
    nationality: str | None = Field(default=None, examples=["COL"])
    document_type: str | list[str] | None = Field(
        default=None, examples=["cedula_ciudadania", "ppt,pasaporte"]
    )


class CheckDocumentationResponse(BaseModel):
    success: bool
    approved: bool | None = None
    reason: str | None = None
    normalized_documents: list[str] | None = None
    errors: str | None = None
