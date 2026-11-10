"""Reglas puras de la consulta de afiliación en salud (BDUA de ADRES). No sabe nada de HTTP.

La consulta la hace el proveedor Croma (``services/croma_client.py``); aquí se normaliza lo que entra
(tipo y número de documento) y se da forma a lo que vuelve. El proveedor documenta estos campos de la
respuesta: ``found``, ``full_name``, ``department``, ``municipality`` y ``affiliations[]`` con ``entity``,
``regime``, ``status``, ``effective_date``, ``termination_date`` y ``affiliate_type``. Una fecha de
terminación ``31/12/2999`` significa que la afiliación sigue vigente con esa entidad.
"""

from __future__ import annotations

import re
from typing import Any

DOCUMENT_TYPES = ("CC", "TI", "CE", "RC", "PA", "PEP", "PPT")
NO_TERMINATION_DATE = "31/12/2999"

# Sigla del proveedor -> alias aceptados (ya sin tildes, en minúsculas, con "_" en vez de espacios).
_ALIASES: dict[str, tuple[str, ...]] = {
    "CC": ("cc", "c.c", "cedula_de_ciudadania", "cedula_ciudadania", "cedula"),
    "TI": ("ti", "t.i", "tarjeta_de_identidad", "tarjeta_identidad"),
    "CE": ("ce", "c.e", "cedula_de_extranjeria", "cedula_extranjeria"),
    "RC": ("rc", "r.c", "registro_civil"),
    "PA": ("pa", "pasaporte", "passport"),
    "PEP": ("pep", "permiso_especial_de_permanencia", "permiso_especial_permanencia"),
    "PPT": (
        "ppt",
        "permiso_por_proteccion_temporal",
        "permiso_de_proteccion_temporal",
        "permiso_proteccion_temporal",
    ),
}
_ALIAS_TO_TYPE = {alias: code for code, aliases in _ALIASES.items() for alias in aliases}

_MIN_NUMBER_LENGTH = 3
_MAX_NUMBER_LENGTH = 30
_NUMBER_NOISE = re.compile(r"[\s.\-]")  # "1.234.567.890", "1 234 567 890", "123-456"
_ACCENTS = str.maketrans("áéíóúüñ", "aeiouun")


def normalize_document_type(raw: Any) -> str | None:
    """Turns a document type into the provider's abbreviation.

    Accepts the abbreviations in either case (``cc``, ``PPT``) and the long names
    (``cedula_de_ciudadania``, ``permiso_por_proteccion_temporal``), with or without accents or underscores.

    Args:
        raw: What the caller sent.

    Returns:
        One of ``DOCUMENT_TYPES``, or None when it is empty or not recognised.
    """
    if raw is None:
        return None
    text = str(raw).strip().lower().translate(_ACCENTS)
    text = re.sub(r"[\s\-]+", "_", text)
    return _ALIAS_TO_TYPE.get(text)


def normalize_document_number(raw: Any) -> str | None:
    """Cleans a document number: no spaces, dots or hyphens.

    Args:
        raw: What the caller sent (a string or a number).

    Returns:
        The cleaned number, or None when it is empty or its length is outside 3-30 characters.
    """
    if raw is None:
        return None
    number = _NUMBER_NOISE.sub("", str(raw))
    if not (_MIN_NUMBER_LENGTH <= len(number) <= _MAX_NUMBER_LENGTH):
        return None
    return number


def prepare_lookup(
    raw_document_type: Any, raw_document_number: Any
) -> tuple[dict[str, str] | None, str | None]:
    """Validates the input and builds the provider's request body.

    An invalid input is a normal business result (``error`` explains why), not an exception, like the
    other tools of this plugin.

    Args:
        raw_document_type: Document type as the caller sent it.
        raw_document_number: Document number as the caller sent it.

    Returns:
        ``({"document_type", "document_number"}, None)`` when valid, otherwise ``(None, error)``.
    """
    document_type = normalize_document_type(raw_document_type)
    if document_type is None:
        accepted = ", ".join(DOCUMENT_TYPES)
        return None, f"document_type is required and must be one of {accepted} (or the full document name)."
    document_number = normalize_document_number(raw_document_number)
    if document_number is None:
        return None, "document_number is required and must have 3 to 30 characters."
    return {"document_type": document_type, "document_number": document_number}, None


def _is_active(termination_date: Any) -> bool:
    return str(termination_date or "").strip() in (NO_TERMINATION_DATE, "2999-12-31")


def build_result(data: dict[str, Any] | None) -> dict[str, Any]:
    """Shapes the provider's answer into the tool's output fields.

    Args:
        data: The ``data`` object of the provider's response (None is treated as "not found").

    Returns:
        ``found``, ``full_name``, ``department``, ``municipality``, ``affiliations`` (each with ``active``) and
        ``has_active_affiliation``.
    """
    data = data or {}
    found = bool(data.get("found"))
    affiliations = []
    for item in (data.get("affiliations") or []) if found else []:
        affiliations.append(
            {
                "entity": item.get("entity"),
                "regime": item.get("regime"),
                "status": item.get("status"),
                "effective_date": item.get("effective_date"),
                "termination_date": item.get("termination_date"),
                "affiliate_type": item.get("affiliate_type"),
                "active": _is_active(item.get("termination_date")),
            }
        )
    return {
        "found": found,
        "full_name": data.get("full_name") if found else None,
        "department": data.get("department") if found else None,
        "municipality": data.get("municipality") if found else None,
        "affiliations": affiliations,
        "has_active_affiliation": any(a["active"] for a in affiliations),
    }
