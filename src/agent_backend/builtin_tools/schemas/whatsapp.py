"""Request and response of the built-in WhatsApp tools (a template, a file)."""

from pydantic import BaseModel, ConfigDict, Field


class GhlSendWhatsappTemplate(BaseModel):
    contact_id: str = Field(..., alias="contactId", description="ID del contacto en GHL que recibe el mensaje")
    template_name: str = Field(..., alias="templateName", description="Nombre de la plantilla en GHL (ej. sam_fc_es)")
    language: str = Field(..., description="Idioma de la plantilla tal como lo muestra GHL (es, en_US, pt_BR)")
    body_variables: list[str] | str | None = Field(
        None,
        alias="bodyVariables",
        description="Valores de las variables del cuerpo, en orden: una lista, un JSON o textos separados por comas. "
        "Un texto como {{contact.first_name}} lo resuelve GHL.",
    )
    header_variables: list[str] | str | None = Field(
        None, alias="headerVariables", description="Valores de las variables del encabezado, en orden (casi nunca hay)"
    )
    category: str = Field("UTILITY", description="Categoría de la plantilla: UTILITY, MARKETING o AUTHENTICATION")
    from_number_id: str | None = Field(
        None, alias="fromNumberId", description="ID del número de WhatsApp remitente; si falta, el predeterminado"
    )
    to_number: str | None = Field(
        None, alias="toNumber", description="Número de WhatsApp del contacto en formato internacional (opcional)"
    )
    location_id: str | None = Field(
        None,
        alias="locationId",
        description="ID de la ubicación (subcuenta) del contacto: elige el token que la administra",
    )

    model_config = ConfigDict(populate_by_name=True)


class GhlSendWhatsappFile(BaseModel):
    contact_id: str = Field(..., alias="contactId", description="ID del contacto en GHL que recibe el archivo")
    file_url: str = Field(..., alias="fileUrl", description="URL pública (http o https) del archivo")
    file_type: str | None = Field(
        None,
        alias="fileType",
        description="image, video, audio o document; si falta se deduce de la extensión (document si no se reconoce)",
    )
    file_name: str | None = Field(
        None, alias="fileName", description="Nombre que ve quien lo recibe; si falta se toma de la URL"
    )
    message: str | None = Field(None, description="Texto que acompaña al archivo (opcional)")
    from_number: str | None = Field(None, alias="fromNumber", description="Número de WhatsApp remitente (opcional)")
    location_id: str | None = Field(
        None,
        alias="locationId",
        description="ID de la ubicación (subcuenta) del contacto: elige el token que la administra",
    )

    model_config = ConfigDict(populate_by_name=True)


class GhlSendWhatsappResponse(BaseModel):
    success: bool
    message_id: str | None = Field(None, description="ID del mensaje que creó GHL")
    conversation_id: str | None = Field(None, description="ID de la conversación del contacto")
    errors: str | None = None
