from pydantic import BaseModel, Field


class CheckAdresRequest(BaseModel):
    document_type: str | None = Field(
        default=None,
        examples=["CC", "cc", "cedula_de_ciudadania"],
        description=(
            "CC, TI, CE, RC, PA, PEP o PPT (en mayúscula o minúscula), o el nombre completo: cedula_de_ciudadania, "
            "tarjeta_de_identidad, cedula_de_extranjeria, registro_civil, pasaporte, permiso_especial_de_permanencia, "
            "permiso_por_proteccion_temporal."
        ),
    )
    document_number: str | int | None = Field(
        default=None,
        examples=["1234567890"],
        description="Número del documento, de 3 a 30 caracteres. Se ignoran espacios, puntos y guiones.",
    )


class AdresAffiliation(BaseModel):
    entity: str | None = Field(default=None, description="EPS de la afiliación.")
    regime: str | None = Field(default=None, description="CONTRIBUTIVO o SUBSIDIADO.")
    status: str | None = None
    effective_date: str | None = None
    termination_date: str | None = Field(
        default=None, description="31/12/2999 significa que la afiliación sigue vigente con esa entidad."
    )
    affiliate_type: str | None = None
    active: bool = Field(default=False, description="True cuando termination_date es 31/12/2999.")


class CheckAdresResponse(BaseModel):
    success: bool
    document_type: str | None = Field(default=None, description="Sigla normalizada que se consultó.")
    found: bool | None = Field(
        default=None, description="False si el documento no está registrado en la BDUA."
    )
    full_name: str | None = None
    department: str | None = None
    municipality: str | None = None
    has_active_affiliation: bool | None = None
    affiliations: list[AdresAffiliation] = Field(default_factory=list)
    errors: str | None = None
