
from pydantic import BaseModel, ConfigDict, Field


class CustomValueUpdate(BaseModel):
    locationId: str = Field(..., description="ID de la subcuenta/ubicación en GHL")
    name: str = Field(..., description="Nombre del Custom Value a actualizar (ej. 'language')")
    value: str = Field(..., description="Nuevo valor para el Custom Value")

class CustomValueResponse(BaseModel):
    success: bool
    id: str | None = None
    name: str | None = None
    value: str | None = None
    errors: str | None = None

class GhlCustomValue(BaseModel):
    id: str
    name: str | None = None
    fieldKey: str | None = None
    value: str | None = None

class GhlCustomValuesList(BaseModel):
    customValues: list[GhlCustomValue]

class GhlCustomFieldUpdate(BaseModel):
    name: str = Field(..., description="Nombre o ID del campo o valor personalizado (ej: 'language', 'uWLes...')")
    value: str = Field(..., description="Nuevo valor a asignar")
    contact_id: str | None = Field(None, alias="contactId", description="ID del contacto (para campos personalizados del usuario)")
    location_id: str | None = Field(None, alias="locationId", description="ID de la ubicación (para valores globales o para resolver nombres)")
    
    model_config = ConfigDict(populate_by_name=True)

class GhlCustomUpdateResponse(BaseModel):
    success: bool
    type: str  # 'contact' o 'custom_value'
    field_id: str | None = Field(None, alias="fieldId")
    field_name: str | None = Field(None, alias="fieldName")
    value: str | None = None
    errors: str | None = None

    model_config = ConfigDict(populate_by_name=True)
