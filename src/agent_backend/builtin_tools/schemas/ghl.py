from typing import Any

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
    name: str = Field(
        ..., description="Nombre o ID del campo o valor personalizado (ej: 'language', 'uWLes...')"
    )
    value: str = Field(..., description="Nuevo valor a asignar")
    contact_id: str | None = Field(
        None, alias="contactId", description="ID del contacto (para campos personalizados del usuario)"
    )
    location_id: str | None = Field(
        None,
        alias="locationId",
        description="ID de la ubicación (para valores globales o para resolver nombres)",
    )

    model_config = ConfigDict(populate_by_name=True)


class GhlCustomUpdateResponse(BaseModel):
    success: bool
    type: str  # 'contact' o 'custom_value'
    field_id: str | None = Field(None, alias="fieldId")
    field_name: str | None = Field(None, alias="fieldName")
    value: str | None = None
    errors: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class GhlAddTags(BaseModel):
    tags: list[str] | str = Field(
        ...,
        description="Etiquetas a agregar: una lista, o un texto con una lista o nombres separados por comas.",
    )
    contact_id: str = Field(..., alias="contactId", description="ID del contacto en GHL")
    location_id: str | None = Field(
        None,
        alias="locationId",
        description="ID de la ubicación (subcuenta) del contacto: elige el token que la administra",
    )

    model_config = ConfigDict(populate_by_name=True)


class GhlAddTagsResponse(BaseModel):
    success: bool
    tags: list[str] | None = Field(None, description="Todas las etiquetas que tiene el contacto ahora")
    tags_added: list[str] | None = Field(None, description="Las etiquetas que se agregaron en esta llamada")
    errors: str | None = None


class GhlRemoveTagsResponse(BaseModel):
    success: bool
    tags: list[str] | None = Field(None, description="Las etiquetas que le quedan al contacto")
    tags_removed: list[str] | None = Field(None, description="Las etiquetas que tenía y se quitaron en esta llamada")
    errors: str | None = None


class GhlGetContact(BaseModel):
    contact_id: str = Field(..., alias="contactId", description="ID del contacto en GHL")
    location_id: str | None = Field(
        None,
        alias="locationId",
        description="ID de la ubicación (subcuenta): elige el token y permite dar los campos personalizados por nombre",
    )

    model_config = ConfigDict(populate_by_name=True)


class GhlGetContactResponse(BaseModel):
    success: bool
    contact_id: str | None = None
    fields: dict[str, Any] | None = Field(
        None, description="Los datos del contacto que tienen valor (nombre, correo, teléfono, dirección, país...)"
    )
    tags: list[str] | None = Field(None, description="Las etiquetas del contacto")
    custom_fields: dict[str, Any] | None = Field(
        None,
        description="Los campos personalizados con valor: nombre del campo -> valor (o su ID si no se pudo resolver el nombre)",
    )
    errors: str | None = None


class GhlUpdateContact(BaseModel):
    contact_id: str = Field(..., alias="contactId", description="ID del contacto en GHL")
    location_id: str | None = Field(
        None,
        alias="locationId",
        description="ID de la ubicación (subcuenta): elige el token y permite buscar campos personalizados por nombre",
    )
    first_name: str | None = Field(None, alias="firstName")
    last_name: str | None = Field(None, alias="lastName")
    name: str | None = Field(None, description="Nombre completo")
    email: str | None = None
    phone: str | None = None
    address1: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = Field(None, alias="postalCode")
    website: str | None = None
    timezone: str | None = None
    source: str | None = None
    date_of_birth: str | None = Field(None, alias="dateOfBirth", description="Fecha de nacimiento (p. ej. 1990-05-31)")
    country: str | None = Field(None, description="Código de país ISO 3166-1 alpha-2 (p. ej. CO)")
    assigned_to: str | None = Field(None, alias="assignedTo", description="ID del usuario asignado")
    dnd: bool | None = Field(None, description="No molestar en todos los canales")
    custom_fields: list[Any] | dict[str, Any] | str | None = Field(
        None,
        alias="customFields",
        description="Campos personalizados: un mapa nombre->valor, una lista de 'nombre=valor', o de objetos {id|key|name, value}",
    )

    model_config = ConfigDict(populate_by_name=True)


class GhlUpdateContactResponse(BaseModel):
    success: bool
    contact_id: str | None = None
    updated_fields: list[str] | None = Field(None, description="Los campos que se enviaron a GHL")
    errors: str | None = None


class GhlUpdateOpportunity(BaseModel):
    opportunity_id: str = Field(..., alias="opportunityId", description="ID de la oportunidad en GHL")
    location_id: str | None = Field(
        None, alias="locationId", description="ID de la ubicación (subcuenta): elige el token que la administra"
    )
    pipeline_id: str | None = Field(None, alias="pipelineId")
    name: str | None = Field(None, description="Nombre de la oportunidad")
    pipeline_stage_id: str | None = Field(None, alias="pipelineStageId")
    status: str | None = Field(None, description="open, won, lost o abandoned")
    monetary_value: float | str | None = Field(None, alias="monetaryValue", description="Valor monetario (0 o más)")
    forecast_expected_close_date: str | None = Field(None, alias="forecastExpectedCloseDate")
    forecast_probability: float | str | None = Field(None, alias="forecastProbability")
    assigned_to: str | None = Field(None, alias="assignedTo", description="ID del usuario asignado")
    lost_reason_id: str | None = Field(None, alias="lostReasonId", description="Solo cuenta si el estado es o pasa a lost")
    custom_fields: list[Any] | dict[str, Any] | str | None = Field(
        None,
        alias="customFields",
        description="Campos personalizados por id o key: un mapa clave->valor, una lista de 'clave=valor', o de objetos",
    )

    model_config = ConfigDict(populate_by_name=True)


class GhlUpdateOpportunityResponse(BaseModel):
    success: bool
    opportunity_id: str | None = None
    updated_fields: list[str] | None = Field(None, description="Los campos que se enviaron a GHL")
    status: str | None = None
    pipeline_id: str | None = None
    pipeline_stage_id: str | None = None
    name: str | None = None
    monetary_value: float | None = None
    errors: str | None = None
