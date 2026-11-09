"""
Module.

    Reglas de negocio puras: cuántos días han pasado desde una fecha dada hasta
    hoy, y si ese número alcanza o supera un umbral. No sabe nada de HTTP.
    Generalización de "check_year_elapsed" del flujo de GHL — el original solo
    comparaba contra un año fijo (resta de año calendario vía setFullYear); a
    pedido del owner (2026-08-27) el umbral ahora es un número de días
    configurable (365, 500, o cualquier otro), calculado como diferencia exacta
    de días calendario en vez de resta de año calendario.
"""

import re
from datetime import date
from typing import Any, Optional, Tuple


def parse_ymd_date(raw: str) -> date:
    """Parsea una fecha en formato YYYY/MM/DD o YYYY-MM-DD.
    """
    parts = re.split(r"[/\-]", raw)
    if len(parts) != 3 or len(parts[0]) != 4:
        raise ValueError("Formato invalido, se esperaba YYYY-MM-DD o YYYY/MM/DD")
    year, month, day = (int(p) for p in parts)
    return date(year, month, day)


def parse_days_threshold(raw: Any) -> Optional[int]:
    """Convierte el umbral de días a un entero positivo, o None si no es válido.
    """
    if raw is None:
        return None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def check_days_elapsed(input_date: date, today: date, days_threshold: int) -> Tuple[bool, int]:
    """Devuelve (elapsed, days_elapsed): si transcurrieron >= days_threshold días entre input_date y today.
    """
    days_elapsed = (today - input_date).days
    return days_elapsed >= days_threshold, days_elapsed
