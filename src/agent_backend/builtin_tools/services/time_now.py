"""Regla de negocio pura: hora actual en una zona horaria dada. No sabe nada de HTTP.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def get_current_time(tz_name: str) -> str:
    """Hora actual en tz_name, en formato ISO 8601 con offset."""
    return datetime.now(ZoneInfo(tz_name)).isoformat()


def get_calendar(tz_name: str, days: int = 21) -> str:
    """Calendario de los próximos días en tz_name, hoy incluido, como "YYYY-MM-DD Weekday" separados por coma.

    Permite resolver "el miércoles" o "mañana" a una fecha sin aritmética de calendario.

    Args:
        tz_name: IANA timezone identifier.
        days: How many days to list, starting today.

    Returns:
        The calendar string.
    """
    today = datetime.now(ZoneInfo(tz_name)).date()
    return ", ".join((today + timedelta(days=i)).strftime("%Y-%m-%d %A") for i in range(days))
