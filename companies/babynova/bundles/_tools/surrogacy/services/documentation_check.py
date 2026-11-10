"""
Module.

    Reglas de negocio puras de validación de documentación por nacionalidad. No
    sabe nada de HTTP. Port 1:1 del código JS del nodo "Check Documentation Logic"
    del flujo de GHL "check_documentation", con modificaciones explícitas del
    owner: el PPT (Permiso de Protección Temporal) también aprueba a un
    extranjero, no solo la Cédula de Ciudadanía (2026-08-26); document_type
    ahora acepta más de un documento por candidato -- string separado por comas
    o lista -- aprobando si CUALQUIERA de ellos es un tipo válido (2026-08-27);
    y las llaves de salida y el texto de "reason" están en inglés, salvo
    "normalized_documents" -- nombres propios de documentos colombianos, que se
    dejan en español (2026-08-27).
"""

import re

_NATIONALITY_RE = re.compile(r"^[A-Z]{3}$")

_DOCUMENT_ALIASES = {
    "cedula_ciudadania": [
        "cedula_ciudadania", "cedula de ciudadania", "cedula ciudadania",
        "c.c", "cc", "cedula de ciudadana",
    ],
    "cedula_extranjeria": [
        "cedula_extranjeria", "cedula de extranjeria", "cedula de extrangeria",
        "cedula extranjeria", "cedula extrangeria", "c.e", "ce",
    ],
    "ppt": [
        "ppt", "permiso de proteccion temporal", "permiso proteccion temporal",
    ],
    "pasaporte": ["pasaporte", "passport", "pass"],
    "otro": ["otro"],
}

# Documentos que hacen apta a una nacionalidad extranjera. Ampliado a pedido
# del owner (2026-08-26): en el JS original solo cedula_ciudadania aprobaba;
# ahora ppt también aprueba.
_APPROVED_FOREIGN_DOCUMENTS = {"cedula_ciudadania", "ppt"}

_APPROVED_REASONS = {
    "cedula_ciudadania": "Foreigner with Colombian Cedula de Ciudadania",
    "ppt": "Foreigner with Permiso de Proteccion Temporal (PPT)",
}


def _split_document_types(raw: str | list[str] | None) -> list[str]:
    """Normaliza el input (string separado por comas, 'y' o 'and', o lista) a una lista de strings sin vacios.
    """
    if raw is None:
        return []
    
    # Separadores comunes en lenguaje natural
    pattern = re.compile(r",\s*|\s+y\s+|\s+and\s+", re.IGNORECASE)
    
    if isinstance(raw, list):
        items = []
        for item in raw:
            # Flatten potential separated strings inside the list
            if isinstance(item, str):
                items.extend(pattern.split(item))
            else:
                items.append(str(item))
    else:
        items = pattern.split(str(raw))
    return [str(item).strip() for item in items if str(item).strip()]


def _resolve_document_type(document_type: str) -> str | None:
    """Busca el tipo canonico de un documento entre sus alias conocidos, o None si no se reconoce.
    """
    doc_clean = document_type.lower()
    for tipo, variaciones in _DOCUMENT_ALIASES.items():
        if doc_clean in variaciones:
            return tipo
    return None


def check_documentation(raw_nationality: str | None, raw_document_type: str | list[str] | None) -> dict[str, bool | str | list[str]]:
    """Valida nacionalidad + tipo(s) de documento y devuelve {approved, reason, normalized_documents}.
    """
    nationality = (raw_nationality or "").strip().upper()

    if not _NATIONALITY_RE.match(nationality):
        reason = (
            "Format error: nationality must be a 3-letter ISO code "
            f"(e.g. COL, VEN, ARG). Received: '{raw_nationality or ''}'"
        )
        return {"approved": False, "reason": reason, "normalized_documents": []}

    if nationality == "COL":
        return {"approved": True, "reason": "Colombian nationality", "normalized_documents": []}

    document_types = _split_document_types(raw_document_type)
    if not document_types:
        return {"approved": False, "reason": "Missing document type for foreign nationality", "normalized_documents": []}

    normalized_documents = []
    approved_type = None
    for document_type in document_types:
        tipo = _resolve_document_type(document_type)
        normalized_documents.append(tipo or "desconocido")
        if approved_type is None and tipo in _APPROVED_FOREIGN_DOCUMENTS:
            approved_type = tipo

    if approved_type is not None:
        return {
            "approved": True,
            "normalized_documents": normalized_documents,
            "reason": _APPROVED_REASONS[approved_type],
        }

    received_documents = ", ".join(f"'{d}'" for d in document_types)
    reason = f"Document not allowed ({received_documents}). Cedula de Ciudadania or PPT is required for non-Colombians."
    return {"approved": False, "normalized_documents": normalized_documents, "reason": reason}
