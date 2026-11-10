"""
Helpers de parsing flexible (texto, booleanos, fechas), usados por servicios de negocio.
"""

import re
import unicodedata
from datetime import date, datetime
from typing import Any, Optional


def normalize(val: Any) -> str:
    """Quita acentos, pasa a mayúsculas y recorta espacios.
    """
    if val is None:
        return ""
    s = unicodedata.normalize("NFD", str(val))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper().strip()


def is_present(val: Any) -> bool:
    """Indica si el valor no es None y no es una cadena vacía tras recortar espacios.
    """
    return val is not None and str(val).strip() != ""


def parse_boolean(val: Any) -> Optional[bool]:
    """Conversión flexible a booleano.

    Devuelve None si no se reconoce el valor.
    """
    if isinstance(val, bool):
        return val
    s = normalize(val)
    if s in ("TRUE", "1", "SI", "YES"):
        return True
    if s in ("FALSE", "0", "NO"):
        return False
    return None


def parse_float(val: Any) -> Optional[float]:
    """Conversión flexible a float.

    Devuelve None si el valor no se puede convertir.
    """
    if val is None:
        return None
    try:
        return float(str(val).strip())
    except (TypeError, ValueError):
        return None


def parse_flexible_date(val: Any) -> Optional[date]:
    """Parser flexible de fechas (YYYY/MM/DD, DD/MM/YYYY, ISO).
    """
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val

    s = str(val).strip()
    if not s:
        return None

    parts = [p.strip() for p in re.split(r"[/\-.]", s)]
    if len(parts) == 3:
        try:
            if len(parts[0]) == 4:
                year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            elif len(parts[2]) == 4:
                day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
            else:
                year = month = day = None
            if year is not None:
                return date(year, month, day)
        except (TypeError, ValueError):
            pass

    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None
