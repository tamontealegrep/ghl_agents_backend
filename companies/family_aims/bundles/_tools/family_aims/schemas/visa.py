from typing import List, Union, Optional
from pydantic import BaseModel, Field

class VisaCheckRequest(BaseModel):
    nationalities: Union[str, List[str]] = Field(
        description="Una o más nacionalidades a revisar. Puede ser una lista o un string separado por comas.",
        examples=["USA", "China, India", ["Spain", "AFG"]]
    )

class VisaCheckResponse(BaseModel):
    success: bool = Field(description="Indica si la consulta se ejecutó correctamente.")
    nationality: str = Field(description="Nacionalidad(es) revisada(s), limpias de espacios.")
    requires_visa: bool = Field(description="Indica si la persona requiere visa para entrar a Colombia (basado en todas sus nacionalidades).")
    conditional_visa: bool = Field(description="Indica si el requisito de visa está condicionado a tener visa USA/Schengen.")
    summary: str = Field(description="Resumen legible de los requisitos encontrados.")
    errors: Optional[str] = Field(default=None, description="Mensaje de error técnico si la consulta falló.")
