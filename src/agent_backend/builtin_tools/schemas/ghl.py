from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

class CustomValueUpdate(BaseModel):
    locationId: str = Field(..., description="ID de la subcuenta/ubicación en GHL")
    name: str = Field(..., description="Nombre del Custom Value a actualizar (ej. 'language')")
    value: str = Field(..., description="Nuevo valor para el Custom Value")

class CustomValueResponse(BaseModel):
    success: bool
    id: Optional[str] = None
    name: Optional[str] = None
    value: Optional[str] = None
    errors: Optional[str] = None

class GhlCustomValue(BaseModel):
    id: str
    name: Optional[str] = None
    fieldKey: Optional[str] = None
    value: Optional[str] = None

class GhlCustomValuesList(BaseModel):
    customValues: List[GhlCustomValue]

class GhlCustomFieldUpdate(BaseModel):
    name: str = Field(..., description="Nombre o ID del campo o valor personalizado (ej: 'language', 'uWLes...')")
    value: str = Field(..., description="Nuevo valor a asignar")
    contact_id: Optional[str] = Field(None, alias="contactId", description="ID del contacto (para campos personalizados del usuario)")
    location_id: Optional[str] = Field(None, alias="locationId", description="ID de la ubicación (para valores globales o para resolver nombres)")
    
    model_config = ConfigDict(populate_by_name=True)

class GhlCustomUpdateResponse(BaseModel):
    success: bool
    type: str  # 'contact' o 'custom_value'
    field_id: Optional[str] = Field(None, alias="fieldId")
    field_name: Optional[str] = Field(None, alias="fieldName")
    value: Optional[str] = None
    errors: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)
